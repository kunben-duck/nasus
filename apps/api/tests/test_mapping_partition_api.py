"""Isolated PG HTTP reads; staging/finalization are not delivered here."""
from copy import deepcopy

from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord
from apps.api.tests.test_test_design_mapping_api import (
    mapping, generation_result, design_scope, publication, documents, evidence_api,
    count, grant_member, completed, submit,
)
from apps.api.tests.test_test_design_results_api import read_result


def test_partition_http_is_private_pinned_read_only_and_old_plan_expires_after_review(mapping):
    v = mapping
    prefix = v["mapping_url"].removesuffix("/mapping-review")
    params = {"artifact_hash": v["generation_metadata"]["artifact_hash"]}
    before = count(v, LLMCallRecord)
    original = deepcopy(v["original_result"])
    response = v["client"].get(prefix + "/mapping-plan", headers=v["headers"], params=params)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    body = response.json()
    assert body["part"] is None and not body["review_authorized"] and not body["execution_authorized"]
    plan = body["plan"]
    assert plan["generation_pin"]["project_id"] == v["project_id"]
    assert plan["generation_pin"]["context_pin"] == original["result"]["context_pin"]
    assert plan["generation_pin"]["scope_pin"] == original["result"]["scope_pin"]
    assert plan["assertion_count"] == len(v["mapping_request"]["mappings"])
    page_params = {**params, "plan_digest": plan["plan_digest"]}
    page = v["client"].get(prefix + "/mapping-parts/0", headers=v["headers"], params=page_params)
    assert page.status_code == 200 and page.headers["cache-control"] == "private, no-store", page.text
    entries = page.json()["part"]["assertions"]
    assert len(entries) == plan["assertion_count"]
    assert set(entries[0]) == {"case_id", "row_id", "step_index", "oracle_digest"}
    assert "artifact_ref" not in page.text and "native-test-design-fixture-key" not in page.text
    assert count(v, TestDesignMappingRecord) == 0 and count(v, LLMCallRecord) == before
    assert v["client"].get(prefix + "/mapping-parts/-1", headers=v["headers"], params=page_params).status_code == 422
    assert v["client"].get(prefix + "/mapping-parts/1", headers=v["headers"], params=page_params).status_code == 400
    assert v["client"].get(prefix + "/mapping-parts/0", headers=v["headers"],
        params={**params, "plan_digest": "sha256:" + "0" * 64}).status_code == 409
    completed(submit(v))
    fresh = v["client"].get(prefix + "/mapping-plan", headers=v["headers"], params=params).json()
    assert fresh["plan"]["expected_previous_revision_id"] is not None
    assert fresh["plan"]["plan_digest"] != plan["plan_digest"]
    assert v["client"].get(prefix + "/mapping-parts/0", headers=v["headers"], params=page_params).status_code == 409
    assert read_result(v, v["generation_metadata"]).json() == original
    assert count(v, TestDesignMappingRecord) == 1 and count(v, LLMCallRecord) == before


def test_partition_http_requires_live_reviewer_and_original_sources(mapping):
    v = mapping
    prefix = v["mapping_url"].removesuffix("/mapping-review")
    params = {"artifact_hash": v["generation_metadata"]["artifact_hash"]}
    grant_member(v)
    denied = v["client"].get(prefix + "/mapping-plan", headers=v["member_headers"], params=params)
    assert denied.status_code == 403, denied.text
    role_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(role_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    view = v["client"].get(prefix + "/mapping-plan", headers=v["member_headers"], params=params)
    assert view.status_code == 200, view.text
    assert v["client"].put(role_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    assert v["client"].get(prefix + "/mapping-parts/0", headers=v["member_headers"],
        params={**params, "plan_digest": view.json()["plan"]["plan_digest"]}).status_code == 403
    assert count(v, TestDesignMappingRecord) == 0
