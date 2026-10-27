import json
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from apps.api.app.main import app
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.reference_link_models import ReferenceAssertionRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT, CASE
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_reference_links_api import candidate


TOOL = "query.system_image.links.candidates"


def invoke(v, *, extra=None, headers=None, key=None):
    target = next(obj for obj in v["document_objects"] if obj["type"] == "SourceAcceptanceCriterion")
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": TOOL, "conversation_id": v["conversation"].json()["id"], "idempotency_key": key,
        "input": {"project_id": v["project_id"], "image_revision_id": candidate(v)["image_revision_id"],
                  "target_object_id": target["id"], "relation": "asserts", **(extra or {})},
    })


def expand(v, result, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{result['id']}/image-query", headers=headers or v["headers"])


def success(response):
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    return response.json()


def test_recall_is_canonical_body_free_replayable_and_never_creates_assertions(documents):
    v = documents
    key = uuid4().hex
    result = success(invoke(v, key=key))
    assert success(invoke(v, key=key))["id"] == result["id"]
    receipt = result["result"]["image_query"]
    assert receipt["operation"] == "link_candidates" and receipt["semantic_status"] == "retrieved_not_asserted"
    assert receipt["request"]["method_version"] == "nasus.link-recall.lexical.v1"
    response = expand(v, result)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    page = response.json()
    assert page["eligible_count"] == page["matched_count"] == 1 and not page["truncated"]
    assert page["target"]["kind"] == "acceptance_criterion" and page["authority_status"] == "pending_confirmation"
    assert "vector_recall_not_run" in page["limitations"]
    item, = page["items"]
    assert item["endpoint"]["kind"] == "test_case" and item["calibrated_probability"] is None
    assert item["status"] == "retrieved_not_asserted"
    assert "explicit_requirement_reference" in item["signals"]
    for endpoint, text in ((page["target"], "Empty input"), (item["endpoint"], "Expected result: HTTP 400")):
        for ident in endpoint["evidence_ids"]:
            evidence = v["client"].get(f"{v['image_url']}/revisions/{page['image_revision_id']}/objects/{endpoint['object_id']}/evidence/{ident}", headers=v["headers"])
            assert evidence.status_code == 200 and text in evidence.json()["content"], evidence.text
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, result["id"])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        assert events and record.result_payload["image_query"] == receipt
        persisted = json.dumps(record.result_payload) + json.dumps([e.event_payload for e in events])
        assert session.scalar(select(func.count()).select_from(ReferenceAssertionRecord).where(ReferenceAssertionRecord.project_id == v["project_id"])) == 0
    for forbidden in ("Empty input", "Search validation", "HTTP", "US-17", "s3://", "local-object://"):
        assert forbidden not in persisted and forbidden not in json.dumps(result)
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    changed = success(invoke(v))
    assert changed["result"]["image_query"]["target"]["revision_id"] != receipt["target"]["revision_id"]
    v["requirement_path"].unlink()
    v["case_path"].unlink()
    assert expand(v, result).json() == page


def test_cases_without_expected_fields_are_gaps_and_empty_matches_are_not_filled(documents):
    v = documents
    v["case_path"].write_text(CASE.replace("Expected result: HTTP 400\n", ""))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    page = expand(v, success(invoke(v))).json()
    assert not page["items"] and page["excluded"] == {"missing_expected_result": 1}
    assert page["eligible_count"] == page["matched_count"] == 0
    page = expand(v, success(invoke(v, extra={"relation": "implements"}))).json()
    assert page["eligible_count"] > 0 and page["matched_count"] == 0 and not page["items"]


def test_recall_reports_limit_and_keeps_each_case_revision(documents):
    v = documents
    v["case_path"].write_text(CASE + "\n" + CASE.replace("TC-9", "TC-10"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    page = expand(v, success(invoke(v, extra={"limit": 1}))).json()
    assert page["eligible_count"] == page["matched_count"] == 2 and page["truncated"] and len(page["items"]) == 1
    full = expand(v, success(invoke(v))).json()
    assert not full["truncated"] and len({item["endpoint"]["revision_id"] for item in full["items"]}) == 2
    assert full["items"][0] == page["items"][0]


def test_recall_rejects_wrong_kinds_foreign_scope_and_invalid_inputs(documents):
    v = documents
    parent = next(obj for obj in v["document_objects"] if obj["type"] == "USWorkItem")
    for extra in ({"target_object_id": parent["id"]}, {"target_object_id": "not-found"}, {"relation": "covers"},
                  {"limit": True}, {"limit": 101}, {"image_revision_id": "not-found"}, {"provider_node_id": "abc"}):
        result = invoke(v, extra=extra)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
        assert result.json()["result"]["image_query"] is None
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": uuid4().hex}).json()["id"]
    assert invoke(v, extra={"project_id": other}).json()["status"] == "failed"


def test_recall_checks_source_permission_on_replay_and_mid_evidence_read(documents, monkeypatch):
    v = documents
    result = success(invoke(v))
    assert expand(v, result, v["member_headers"]).status_code == 403
    grant_member(v)
    assert expand(v, result, v["member_headers"]).status_code == 200
    images = app.state.container.image_revisions
    read_evidence = images.evidence.reader.read
    calls = []

    def revoke(target):
        body = read_evidence(target)
        repo = SourceAccessRepository()
        snapshot = repo.load_snapshot(v["project_id"])
        repo.set_policy(v["project_id"], target.evidence.binding_id, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
                        changed_by=v["owner"]["id"], invocation_id="link-recall-revoked")
        calls.append(True)
        return body

    monkeypatch.setattr(images.evidence.reader, "read", revoke)
    denied = expand(v, result, v["member_headers"])
    assert denied.status_code in (403, 409) and "Search" not in denied.text, denied.text
    assert calls == [True]
    assert expand(v, result, v["member_headers"]).status_code == 403 and calls == [True]


def test_recall_corrupt_or_nonfrozen_field_evidence_cannot_emit_receipt(documents, monkeypatch):
    v = documents
    images = app.state.container.image_revisions
    read_evidence = images.evidence.reader.read

    def corrupt(*args, **kwargs):
        raise EvidenceIntegrityError("private corrupt source text")

    result = success(invoke(v))
    monkeypatch.setattr(images.evidence.reader, "read", corrupt)
    failed = invoke(v)
    assert failed.json()["status"] == "failed" and "private corrupt" not in failed.text
    assert expand(v, result).status_code == 502
    monkeypatch.setattr(images.evidence.reader, "read", read_evidence)
    read_document = images.read_document

    def no_field_evidence(*args, **kwargs):
        page = read_document(*args, **kwargs)
        page["evidence"] = []
        return page

    monkeypatch.setattr(images, "read_document", no_field_evidence)
    failed = invoke(v)
    assert failed.json()["status"] == "failed" and failed.json()["result"]["image_query"] is None
