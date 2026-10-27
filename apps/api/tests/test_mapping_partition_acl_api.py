from uuid import uuid4

from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord
from apps.api.tests.test_test_design_mapping_api import (
    mapping, generation_result, design_scope, publication, documents, evidence_api, count, grant_member,
)


def test_original_source_revocation_invalidates_previously_observed_partition_plan(mapping):
    v = mapping
    prefix = v["mapping_url"].removesuffix("/mapping-review")
    params = {"artifact_hash": v["generation_metadata"]["artifact_hash"]}
    grant_member(v)
    role_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(role_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    observed = v["client"].get(prefix + "/mapping-plan", headers=v["member_headers"], params=params)
    assert observed.status_code == 200, observed.text
    repository = SourceAccessRepository()
    current = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=current.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
    for suffix, values in (("/mapping-plan", params), ("/mapping-parts/0", {
            **params, "plan_digest": observed.json()["plan"]["plan_digest"]})):
        denied = v["client"].get(prefix + suffix, headers=v["member_headers"], params=values)
        assert denied.status_code == 403, denied.text
        assert "generation_pin" not in denied.text and "assertions" not in denied.text
    assert v["client"].get(prefix + "/mapping-plan", headers=v["headers"], params=params).status_code == 200
    assert count(v, TestDesignMappingRecord) == 0
