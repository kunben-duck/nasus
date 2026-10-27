import json
from uuid import uuid4

from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, evaluate, submit, completed
from apps.api.tests.test_source_access_api import grant_member


TOOL = "query.system_image.links.semantic_decisions"


def query(v, review, *, headers=None, key=None, **selection):
    payload = {name: review[name] for name in ("project_id", "evaluation_id", "subject_object_id")}
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": {**payload, **selection}, "idempotency_key": key or uuid4().hex,
        "initiator_surface": "agent_loop", "initiator_actor": "agent"})


def expand(v, invocation, *, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{invocation['id']}/image-query", headers=headers or v["headers"])


def test_semantic_history_receipts_pin_empty_and_nonempty_heads_and_keep_private_bodies_out_of_outbox(semantic):
    v = semantic
    url, review, original = evaluate(v)
    assert TOOL in {item["tool_id"] for item in v["client"].get("/v1/tools/catalog", headers=v["headers"]).json()}
    empty = completed(query(v, review))
    assert expand(v, empty).json() == original
    completed(submit(v, review))
    before = v["client"].get(url, headers=v["headers"]).json()
    key = uuid4().hex
    first = completed(query(v, review, key=key))
    receipt = first["result"]["image_query"]
    assert receipt["head_decision_id"] == before["head_decision_id"]
    assert receipt["decision_ids"] == [before["head_decision_id"]]
    assert receipt["claim_id"] == original["assertion"]["claim_id"]
    assert receipt["evaluation_artifact_hash"] == original["assertion"]["evaluation_artifact_hash"]
    assert completed(query(v, review, key=key))["id"] == first["id"]
    assert query(v, review, key=key, limit=1).status_code == 409
    completed(submit(v, {**review, "expected_previous_decision_id": before["head_decision_id"],
        "decision": "defer", "reason": "Wait for independent authority"}))
    history = completed(query(v, review, limit=1))
    page = expand(v, history)
    assert page.status_code == 200 and page.headers["cache-control"] == "private, no-store"
    assert page.json()["total"] == 2 and page.json()["next_offset"] == 1
    assert history["result"]["next_recommended_tools"] == [TOOL, "query.system_image.links.decision_applicability"]
    last = completed(query(v, review, through_decision_id=history["result"]["image_query"]["head_decision_id"], offset=1, limit=1))
    assert expand(v, last).json()["items"][0]["decision"] == "defer"
    assert expand(v, first).json() == before
    assert expand(v, empty).json() == original
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_images.describe(first["id"], v["project_id"]) == receipt
    for result in (empty, first, history, last):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, result["id"])
            events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
            assert events and row.result_payload["image_query"] == result["result"]["image_query"]
            persisted = json.dumps(row.result_payload) + json.dumps([event.event_payload for event in events])
        for private in (review["reason"], "Wait for independent authority", "reason_summary", "private-provider-key", "local-object://", "s3://"):
            assert private not in persisted
    assert len(v["calls"]) == 1


def test_semantic_history_query_enforces_typed_scope_and_current_project_and_source_access(semantic):
    v = semantic
    _, review, _ = evaluate(v)
    completed(submit(v, review))
    for selection in ({"limit": True}, {"limit": 51}, {"offset": "0"}, {"offset": 1001}, {"through_decision_id": "foreign"},
                      {"subject_object_id": "foreign"}, {"evaluation_id": "foreign"}, {"file_path": "/etc/passwd"}):
        result = query(v, review, **selection)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
        assert result.json()["result"]["image_query"] is None
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Foreign semantic query"}).json()["id"]
    assert query(v, review, project_id=other).json()["status"] == "failed"
    grant_member(v)
    member = completed(query(v, review, headers=v["member_headers"]))
    assert expand(v, member, headers=v["member_headers"]).status_code == 200
    assert v["client"].get(f"/v1/tool-invocations/{member['id']}/image-query").status_code == 401
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].delete(member_url, headers=v["headers"]).status_code == 200
    assert expand(v, member, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    access = SourceAccessRepository()
    snapshot = access.load_snapshot(v["project_id"])
    access.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="semantic-history-revoke")
    denied = expand(v, member, headers=v["member_headers"])
    assert denied.status_code == 403 and review["reason"] not in denied.text
    assert query(v, review, headers=v["member_headers"]).json()["status"] == "failed"
    assert len(v["calls"]) == 1


def test_semantic_history_replay_rejects_forged_receipts_and_reauthorizes_after_read(semantic, monkeypatch):
    v = semantic
    _, review, _ = evaluate(v)
    completed(submit(v, review))
    first = completed(query(v, review))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, first["id"])
        row.result_payload = {**row.result_payload, "image_query": {
            **row.result_payload["image_query"], "result_hash": "sha256:" + "0" * 64}}
    broken = expand(v, first)
    assert broken.status_code == 502 and review["reason"] not in broken.text
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, first["id"])
        row.result_payload = {**first["result"], "image_query": {**first["result"]["image_query"],
            "request": {**first["result"]["image_query"]["request"], "subject_object_id": "forged"}}}
    assert expand(v, first).status_code == 409
    grant_member(v)
    member = completed(query(v, review, headers=v["member_headers"]))
    repo = app.state.container.semantic_reviews.repository
    history = repo.history
    def revoke(*args):
        result = history(*args)
        access = SourceAccessRepository()
        snapshot = access.load_snapshot(v["project_id"])
        access.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="semantic-history-revoke-mid-read")
        return result
    monkeypatch.setattr(repo, "history", revoke)
    denied = expand(v, member, headers=v["member_headers"])
    assert denied.status_code in {403, 409} and review["reason"] not in denied.text
