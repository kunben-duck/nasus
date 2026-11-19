from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignCaseEditRecord as Edit
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_results_api import generation_result, design_scope, publication, documents, evidence_api, commit, read_result, count
from apps.api.tests.test_test_design_mapping_api import mapping, submit, inspect
from apps.api.tests.test_requirement_reviews_api import command


def edit_request(v, archive):
    case = deepcopy(archive["result"]["proposal"]["cases"][0])
    case["title"] += " (clarified setup)"
    case["preconditions"].append("Use an isolated account for this case")
    return {"project_id": v["project_id"], "generation_id": archive["metadata"]["generation_id"],
        "generation_artifact_hash": archive["metadata"]["artifact_hash"], "cases": [case], "reason": "Clarify setup without changing expectations"}


def test_edit_preserves_model_output_supersedes_mapping_and_requires_new_review(mapping):
    v = mapping
    assert submit(v).json()["status"] == "completed"
    assert inspect(v).json()["head"]["current_use"]["mapping_current"]
    original = v["original_result"]
    calls = count(v, LLMCallRecord)
    request = edit_request(v, original)
    done = command(v, "quality.test_design.cases.revise", request, key="case-edit")
    assert done["status"] == "completed", done.get("summary")
    ident = done["result"]["object_refs"][0].split(":", 1)[1]
    edited = read_result(v, {"generation_id": ident}).json()
    assert edited["result"]["schema"] == "nasus.test-design-case-revision.v1"
    assert edited["metadata"]["call_id"] is None and "raw_output" not in edited["result"]
    assert edited["result"]["parent"]["generation_id"] == original["metadata"]["generation_id"]
    assert edited["result"]["changes"][0]["before"] == original["result"]["proposal"]["cases"][0]
    assert edited["result"]["proposal"]["cases"][0] == request["cases"][0]
    assert edited["current_use"]["scope_current"]
    old = read_result(v, original["metadata"]).json()
    assert old["result"] == original["result"] and not old["current_use"]["scope_current"]
    assert not inspect(v).json()["head"]["current_use"]["mapping_current"]
    assert count(v, LLMCallRecord) == calls and count(v, Edit) == 1
    replay = command(v, "quality.test_design.cases.revise", request, key="case-edit")
    assert replay["id"] == done["id"] and replay["status"] == "completed"
    assert command(v, "quality.test_design.cases.revise", request)["status"] == "failed"
    second = command(v, "quality.test_design.cases.revise", edit_request(v, edited))
    assert second["status"] == "completed", second.get("summary")
    assert count(v, Edit) == 2
    with pytest.raises(IntegrityError, match="append-only"):
        with session_scope() as session:
            session.execute(delete(Edit).where(Edit.project_id == v["project_id"]))


@pytest.mark.parametrize("change", ["oracle", "assertion", "foreign_case", "empty_change", "hash"])
def test_edit_rejects_changed_business_expectations_and_invalid_parent(generation_result, change):
    v = generation_result
    archive = read_result(v, commit(v)).json()
    request = edit_request(v, archive)
    if change == "oracle":
        request["cases"][0]["assertions"][0]["oracle"]["expected_result"] = "Allow unauthorized edit"
    elif change == "assertion":
        request["cases"][0]["assertions"].pop()
    elif change == "foreign_case":
        request["cases"][0]["case_id"] = "other-case"
    elif change == "empty_change":
        request["cases"] = archive["result"]["proposal"]["cases"]
    else:
        request["generation_artifact_hash"] = "sha256:" + "f" * 64
    result = command(v, "quality.test_design.cases.revise", request)
    assert result["status"] == "failed", result
    assert count(v, Edit) == 0
    assert read_result(v, archive["metadata"]).json() == archive


def test_concurrent_edits_have_exactly_one_current_child(generation_result):
    v = generation_result
    original = read_result(v, commit(v)).json()
    request = edit_request(v, original)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda reason: command(v, "quality.test_design.cases.revise", {
            **request, "reason": reason}), ["Editor A clarification", "Editor B clarification"]))
    assert sorted(item["status"] for item in results) == ["completed", "failed"], results
    assert count(v, Edit) == 1
    assert not read_result(v, original["metadata"]).json()["current_use"]["scope_current"]


def test_case_edit_outbox_failure_rolls_back_child_and_keeps_parent_current(generation_result, monkeypatch):
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignResultRecord as Result
    v = generation_result
    original = read_result(v, commit(v)).json()
    before = count(v, Result)
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.test_design.revised":
            raise RuntimeError("injected case revision outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    result = command(v, "quality.test_design.cases.revise", edit_request(v, original))
    assert result["status"] == "failed", result
    assert count(v, Edit) == 0 and count(v, Result) == before
    assert read_result(v, original["metadata"]).json() == original


def test_case_revision_read_and_receipt_reauthorize_sources(generation_result):
    from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
    from apps.api.app.domain.system_image.source_access import SourceAccessRule
    v = generation_result
    original = read_result(v, commit(v)).json()
    assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    done = command(v, "quality.test_design.cases.revise", edit_request(v, original), headers=v["member_headers"])
    assert done["status"] == "completed", done
    child_id = done["result"]["object_refs"][0].split(":", 1)[1]
    access = SourceAccessRepository()
    snapshot = access.load_snapshot(v["project_id"])
    access.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-case-edit")
    for url in (f"/v1/projects/{v['project_id']}/quality/test-design-results/{child_id}", f"/v1/tool-invocations/{done['id']}"):
        response = v["client"].get(url, headers=v["member_headers"])
        assert response.status_code == 403, response.text


def test_edited_cases_can_receive_new_independent_mapping_review(generation_result, monkeypatch):
    from apps.api.app.main import app
    from sqlalchemy import select
    from apps.api.app.infrastructure.persistence.derivation_registry_models import DerivationRegistryRecord as Node
    from apps.api.tests.test_test_design_mapping import reviews
    v = generation_result
    original = read_result(v, commit(v)).json()
    edited = command(v, "quality.test_design.cases.revise", edit_request(v, original))
    assert edited["status"] == "completed", edited
    ident = edited["result"]["object_refs"][0].split(":", 1)[1]
    child = read_result(v, {"generation_id": ident}).json()
    with session_scope() as session:
        registrations = session.scalars(select(Node).where(Node.project_id == v["project_id"],
            Node.invocation_id == edited["id"])).all()
        assert {row.node_key for row in registrations} == {"generation:" + ident, "coverage:" + ident,
            *("case:" + ident + "/" + case["case_id"] for case in child["result"]["proposal"]["cases"])}
    assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    failures = []
    service = app.state.container.test_design_mappings
    review = service.review
    def observe(*args, **kwargs):
        try:
            return review(*args, **kwargs)
        except Exception as exc:
            failures.append(repr(exc))
            raise
    monkeypatch.setattr(service, "review", observe)
    result = command(v, "quality.test_design_mapping.review", {
        "project_id": v["project_id"], "generation_id": ident,
        "generation_artifact_hash": child["metadata"]["artifact_hash"],
        "expected_previous_revision_id": None, "decision": "review", "reason": "Independent review of edited cases",
        "mappings": reviews(child["result"]["proposal"])}, headers=v["member_headers"])
    assert result["status"] == "completed", failures or result
    response = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{ident}/mapping-review",
        headers=v["member_headers"], params={"artifact_hash": child["metadata"]["artifact_hash"]})
    assert response.status_code == 200, response.text
    assert response.json()["head"]["current_use"]["mapping_complete"]
    assert not response.json()["head"]["current_use"]["execution_authorized"]
