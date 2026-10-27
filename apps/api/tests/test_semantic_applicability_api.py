import json
from uuid import uuid4

from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, evaluate, submit, support, completed
from apps.api.tests.test_semantic_membership_api import freeze, child
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_document_projection_api import REQUIREMENT
from apps.api.tests.test_source_access_api import grant_member


TOOL = "query.system_image.links.decision_applicability"


def query(v, page, image, *, headers=None, key=None, **changes):
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": TOOL, "conversation_id": v["conversation"].json()["id"],
        "idempotency_key": key or uuid4().hex, "initiator_surface": "agent_loop", "initiator_actor": "agent",
        "input": {"project_id": v["project_id"], "image_revision_id": image["image_revision_id"],
            "expected_image_hash": image["artifact_hash"], "source_decision_id": page["head_decision_id"],
            "subject_object_id": page["assertion"]["subject_object_id"], "target_object_id": page["assertion"]["object_id"], **changes}})


def expand(v, invocation, *, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{invocation['id']}/image-query", headers=headers or v["headers"])


def setup(v):
    url, review, _ = evaluate(v)
    completed(submit(v, review))
    page = v["client"].get(url, headers=v["headers"]).json()
    _, frozen = child(v, freeze(v, {"project_id": v["project_id"], "parent_revision_id": v["request"]["image_revision_id"],
        "parent_artifact_hash": v["request"]["expected_image_hash"], "decision_ids": [page["head_decision_id"]]}))
    return url, review, page, frozen["revision"]


def test_applicability_survives_reingestion_and_receipt_replay_never_transfers_approval(semantic, monkeypatch):
    v = semantic
    support(v, monkeypatch)
    url, review, page, frozen = setup(v)
    key = uuid4().hex
    result = completed(query(v, page, frozen, key=key))
    assert result["result"]["image_query"]["assessment_status"] == "rejected_same_revisions"
    assert result["result"]["image_query"]["candidate_action"] == "exclude_from_unreviewed_candidates"
    assert completed(query(v, page, frozen, key=key))["id"] == result["id"]
    assert query(v, page, frozen, key=key, target_object_id="different").status_code == 409
    first = expand(v, result)
    assert first.status_code == 200 and first.headers["cache-control"] == "private, no-store", first.text
    assert first.json()["image_revision_id"] != first.json()["source_image_revision_id"]
    assert first.json()["assessment"]["status"] == "rejected_same_revisions"
    assert not first.json()["assessment"]["approval_transferred"]
    v["requirement_path"].write_text("\n\n" + REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    new_image = candidate(v)
    changed = completed(query(v, page, new_image))
    comparison = expand(v, changed).json()
    assert comparison["target"]["entity_id"] == comparison["original_target"]["entity_id"]
    assert comparison["target"]["revision_id"] != comparison["original_target"]["revision_id"]
    assert comparison["assessment"]["status"] == "stale_requires_review"
    assert comparison["decision"] == "reject"
    completed(submit(v, {**review, "decision": "accept", "expected_previous_decision_id": page["head_decision_id"]}))
    current = completed(query(v, page, frozen))
    now = expand(v, current).json()
    assert now["decision"] == "accept" and now["head_decision_id"] != page["head_decision_id"]
    assert now["assessment"]["status"] == "same_revisions_review_required" and not now["assessment"]["approval_transferred"]
    assert expand(v, result).json() == first.json()
    assert expand(v, changed).json() == comparison
    assert v["client"].get(url, headers=v["headers"]).json()["total"] == 2
    for item in (result, changed, current):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, item["id"])
            events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == item["id"])).all()
            assert events
            persisted = json.dumps(row.result_payload) + json.dumps([event.event_payload for event in events])
        for private in (review["reason"], "HTTP 400", "HTTP 422", "private-provider-key", "reason_summary", "s3://", "local-object://"):
            assert private not in persisted
    assert len(v["calls"]) == 1


def test_applicability_input_pins_and_revoked_source_access_fail_closed(semantic):
    v = semantic
    _, review, page, frozen = setup(v)
    for changes in ({"source_decision_id": "missing"}, {"through_decision_id": "missing"}, {"through_decision_id": ""},
                    {"subject_object_id": "foreign"}, {"expected_image_hash": "sha256:" + "0" * 64},
                    {"image_revision_id": True}, {"entity_id": "forged"}, {"source_decision_id": 0}):
        result = query(v, page, frozen, **changes)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    grant_member(v)
    result = completed(query(v, page, frozen, headers=v["member_headers"]))
    assert expand(v, result, headers=v["member_headers"]).status_code == 200
    assert v["client"].get(f"/v1/tool-invocations/{result['id']}/image-query").status_code == 401
    access = SourceAccessRepository()
    snapshot = access.load_snapshot(v["project_id"])
    access.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="applicability-revoke")
    denied = expand(v, result, headers=v["member_headers"])
    assert denied.status_code == 403 and review["reason"] not in denied.text
    assert query(v, page, frozen, headers=v["member_headers"]).json()["status"] == "failed"
    assert len(v["calls"]) == 1


def test_applicability_replay_checks_result_request_and_acl_after_read(semantic, monkeypatch):
    v = semantic
    _, review, page, frozen = setup(v)
    result = completed(query(v, page, frozen))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        row.result_payload = {**row.result_payload, "image_query": {**row.result_payload["image_query"], "result_hash": "sha256:" + "0" * 64}}
    assert expand(v, result).status_code == 502
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        row.result_payload = {**result["result"], "image_query": {**result["result"]["image_query"],
            "request": {**result["result"]["image_query"]["request"], "subject_object_id": "forged"}}}
    assert expand(v, result).status_code == 409
    grant_member(v)
    member = completed(query(v, page, frozen, headers=v["member_headers"]))
    service = app.state.container.tool_images.images.semantic_applicability
    endpoint = service._endpoint
    def revoke(*args):
        value = endpoint(*args)
        if args[1] == frozen["image_revision_id"]:
            access = SourceAccessRepository()
            snapshot = access.load_snapshot(v["project_id"])
            access.set_policy(v["project_id"], value.binding_id, SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="applicability-revoke-during-read")
        return value
    monkeypatch.setattr(service, "_endpoint", revoke)
    denied = expand(v, member, headers=v["member_headers"])
    assert denied.status_code in {403, 409} and review["reason"] not in denied.text
