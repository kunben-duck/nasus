"""Actual canonical source capture, context/scope/draft/mapping and isolated PG."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.domain.system_image.derivation_impact import DerivationImpactTooLarge
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignResultRecord
from apps.api.app.infrastructure.persistence.test_design_scope_models import TestDesignScopeRecord
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_test_design_scope_api import design_scope
from apps.api.tests.test_test_design_results_api import generation_result
from apps.api.tests.test_test_design_mapping_api import mapping, submit
from apps.api.tests.test_semantic_evaluations_api import invoke, completed, count
from apps.api.tests.test_source_access_api import grant_member


TOOL = "query.system_image.context.change_impact"


@pytest.fixture
def impact(mapping):
    v = mapping
    completed(submit(v))
    metadata = v["context"]["metadata"]
    image_url = v["image_url"] + "/revisions/" + metadata["image_revision_id"]
    sources = v["client"].get(image_url, headers=v["headers"], params={"section": "source_members"}).json()["items"]
    before = next(item for item in sources if item["source_type"] == "code")
    v["path"].write_text("class Orders:\n    def submit(self):\n        return 'changed dependency fixture'\n")
    v["invoke"]("system_image.sources.ingest")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    after = next(item for item in manifest.members if item.binding_id == before["binding_id"])
    assert before["source_revision_id"] != after.source_revision_id
    request = {"project_id": v["project_id"], "context_id": metadata["context_id"],
        "context_artifact_hash": metadata["artifact_hash"], "before_revision_id": before["source_revision_id"],
        "after_revision_id": after.source_revision_id}
    v.update(impact_request=request, impact_binding=before["binding_id"],
        impact_url=f"{v['image_url']}/context-packs/{metadata['context_id']}/change-impact")
    return v


def read(v, headers=None, **changes):
    return v["client"].get(v["impact_url"], headers=headers or v["headers"],
        params={key: value for key, value in {**v["impact_request"], **changes}.items() if key not in {"project_id", "context_id"}})


def query(v, headers=None, **changes):
    return invoke(v, TOOL, {**v["impact_request"], **changes}, headers=headers, key=uuid4().hex)


def expand(v, result, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{result['id']}/image-query", headers=headers or v["headers"])


def test_actual_context_closure_and_canonical_receipt_are_fixed_verified_and_read_only(impact):
    v = impact
    models = (TestDesignResultRecord, TestDesignScopeRecord, TestDesignMappingRecord, LLMCallRecord)
    before_counts = [count(v, model) for model in models]
    original_context = v["client"].get(f"{v['image_url']}/context-packs/{v['impact_request']['context_id']}", headers=v["headers"]).json()
    response = read(v)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    body = response.json()
    kinds = {node["kind"] for node in body["dependencies"]}
    assert kinds == {"context", "scope", "generation", "case", "coverage", "mapping"}
    assessment = body["assessment"]
    assert set(assessment["affected_keys"]) == {node["kind"] + ":" + node["artifact_id"] for node in body["dependencies"]}
    assert assessment["dependency_closure_complete"] and not assessment["impact_complete"]
    assert not assessment["invalidation_applied"] and not assessment["execution_authorized"]
    assert "query_scope_changed" in assessment["reason_codes"]
    result = completed(query(v))
    receipt = result["result"]["image_query"]
    assert receipt["operation"] == "context_change_impact" and receipt["dependency_count"] == len(body["dependencies"])
    assert expand(v, result).json() == body
    assert [count(v, model) for model in models] == before_counts
    assert v["client"].get(f"{v['image_url']}/context-packs/{v['impact_request']['context_id']}", headers=v["headers"]).json() == original_context
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(result["id"], v["project_id"]) == receipt
    with session_scope() as session:
        stored = session.get(ToolInvocationRecord, result["id"])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        assert stored.result_payload["image_query"] == receipt and events
        durable = json.dumps(stored.result_payload) + json.dumps([event.event_payload for event in events])
    for forbidden in ("Orders", "changed dependency fixture", "HTTP 400", "oracle", "source_fields", "artifact_ref", "local-object://", "s3://"):
        assert forbidden not in durable + response.text
    unchanged = read(v, after_revision_id=v["impact_request"]["before_revision_id"])
    assert unchanged.status_code == 200 and unchanged.json()["assessment"]["affected_keys"] == []
    assert read(v, context_artifact_hash="sha256:" + "0" * 64).status_code == 502
    failed = query(v, invalidation_applied=True)
    assert failed.json()["status"] == "failed" and failed.json()["result"]["image_query"] is None


def test_replay_excludes_new_mapping_records_but_new_query_includes_them(impact):
    v = impact
    result = completed(query(v))
    original = expand(v, result).json()
    review = v["client"].get(v["mapping_url"], headers=v["headers"],
        params={"artifact_hash": v["generation_metadata"]["artifact_hash"]}).json()
    completed(submit(v, {**v["mapping_request"], "expected_previous_revision_id": review["head"]["revision"]["revision_id"],
                        "reason": "Another independent fixture review"}))
    assert expand(v, result).json() == original
    newer = read(v)
    assert newer.status_code == 200, newer.text
    assert len(newer.json()["dependencies"]) == len(original["dependencies"]) + 1
    assert newer.json()["assessment"]["graph_hash"] != original["assessment"]["graph_hash"]


def test_source_revocation_corrupt_artifact_and_complete_budget_fail_closed(impact, monkeypatch):
    v = impact
    assert v["client"].get(v["impact_url"], params=v["impact_request"]).status_code == 401
    grant_member(v)
    result = completed(query(v, headers=v["member_headers"]))
    assert expand(v, result, headers=v["member_headers"]).status_code == 200
    repository = SourceAccessRepository()
    access = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], v["impact_binding"], SourceAccessRule("restricted"),
        expected_epoch=access.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    denied = expand(v, result, headers=v["member_headers"])
    assert denied.status_code in (403, 404) and "affected_keys" not in denied.text, denied.text
    assert query(v, headers=v["member_headers"]).json()["status"] == "failed"
    quality = app.state.container.context_change_impacts.quality
    with monkeypatch.context() as scoped:
        def oversized(*args, **kwargs):
            raise DerivationImpactTooLarge("private fixture")
        scoped.setattr(quality, "read", oversized)
        too_large = read(v)
        assert too_large.status_code == 413 and "private fixture" not in too_large.text
    with monkeypatch.context() as scoped:
        scoped.setattr(app.state.container.test_design_results.artifacts.storage, "get_bytes", lambda *a, **kw: b"corrupt private fixture")
        corrupt = read(v)
        assert corrupt.status_code == 502 and "corrupt private fixture" not in corrupt.text


@pytest.mark.parametrize("phase", ["inventory", "capacity_failure"])
def test_source_revocation_during_inventory_precedes_graph_and_error_diagnostics(impact, monkeypatch, phase):
    v = impact
    grant_member(v)
    inventory = app.state.container.context_change_impacts.quality.inventory
    original = inventory.list
    calls = []
    def revoke(*args):
        selected = original(*args)
        access = SourceAccessRepository().load_snapshot(v["project_id"])
        SourceAccessRepository().set_policy(v["project_id"], v["impact_binding"], SourceAccessRule("restricted"),
            expected_epoch=access.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
        calls.append(True)
        if phase == "capacity_failure":
            raise DerivationImpactTooLarge("private dependency count")
        return selected
    monkeypatch.setattr(inventory, "list", revoke)
    denied = read(v, headers=v["member_headers"])
    assert denied.status_code == 409 and calls == [True], denied.text
    for forbidden in ("affected_keys", "dependencies", "private dependency count", "graph_hash"):
        assert forbidden not in denied.text
