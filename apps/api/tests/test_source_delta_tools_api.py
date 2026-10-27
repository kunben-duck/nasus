"""Canonical ToolRuntime reads against actual HTTP/PG and isolated source archives."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.domain.system_image.source_delta import SourceDeltaPageTooLarge
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_source_delta_api import delta_api


TOOL = "query.system_image.sources.delta"


def invoke(v, *, fields=None, headers=None, conversation_id=None, key=None):
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "conversation_id": conversation_id or v["conversation"].json()["id"], "tool_id": TOOL,
        "input": {"project_id": v["project_id"], **v["params"], **(fields or {})}, "idempotency_key": key,
        "initiator_surface": "agent_loop", "initiator_actor": "agent"})


def completed(response):
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    result = response.json()
    assert result["result"]["image_query"]["operation"] == "source_delta"
    return result


def expand(v, result, *, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{result['id']}/image-query", headers=headers or v["headers"])


def test_delta_tool_persists_body_free_receipt_and_replays_fixed_pages(delta_api):
    v = delta_api
    catalog = v["client"].get("/v1/tools/catalog", headers=v["headers"]).json()
    definition = next(item for item in catalog if item["tool_id"] == TOOL)
    assert definition["confirmation_mode"] == "none" and definition["produced_objects"] == []
    key = uuid4().hex
    result = completed(invoke(v, fields={"limit": 1}, key=key))
    receipt = result["result"]["image_query"]
    assert receipt["total"] == 4 and receipt["next_offset"] == 1
    assert receipt["complete"] and receipt["counts"]["unresolved"] == 0
    assert result["result"]["next_recommended_tools"] == [TOOL]
    assert completed(invoke(v, fields={"limit": 1}, key=key))["id"] == result["id"]
    assert invoke(v, fields={"limit": 2}, key=key).status_code == 409
    page = expand(v, result)
    assert page.status_code == 200 and page.headers["cache-control"] == "private, no-store", page.text
    assert page.json()["content_hash"] == receipt["delta_hash"]
    assert page.json()["before"]["source_revision_id"] == v["before"].source_revision_id
    assert app.state.container.tool_evidence.describe(result["id"], v["project_id"]) == receipt
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        assert events and row.result_payload["image_query"] == receipt
        durable = json.dumps(row.result_payload) + json.dumps([item.event_payload for item in events])
    audit = v["client"].get("/v1/audit-events", headers=v["headers"], params={"tool_invocation_id": result["id"]})
    assert audit.status_code == 200 and "tool.invocation.completed" in audit.text
    for forbidden in ("keep.py", "old.py", "new.py", "before = 3", "manifest_ref", "s3://", "local-object://", str(v["root"])):
        assert forbidden not in durable + json.dumps(result) + audit.text
    next_page = completed(invoke(v, fields={"offset": 1}))
    assert next_page["result"]["image_query"]["delta_hash"] == receipt["delta_hash"]
    assert next_page["result"]["next_recommended_tools"] == []
    rename = completed(invoke(v, fields={"section": "rename_candidates"}))
    assert not expand(v, rename).json()["items"][0]["identity_preserved"]
    # A later capture and removal of the working tree never retarget old pins.
    (v["root"] / "keep.py").write_text("new capture = 5\n")
    v["invoke"]("system_image.sources.ingest")
    for path in v["root"].iterdir():
        path.unlink()
    assert expand(v, result).json() == page.json()


def test_delta_tool_invalid_or_foreign_inputs_never_read_archives(delta_api, monkeypatch):
    v = delta_api
    calls = []
    monkeypatch.setattr(app.state.container.source_deltas.reader, "read", lambda target: calls.append(target))
    for invalid in ({"limit": True}, {"offset": "1"}, {"kind": "accepted"},
                    {"section": "rename_candidates", "kind": "added"}, {"file_path": "/private"},
                    {"before_revision_id": "missing"}, {"publication_authorized": True}):
        response = invoke(v, fields=invalid)
        assert response.status_code == 200 and response.json()["status"] == "failed", response.text
        assert response.json()["result"]["image_query"] is None
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Other {uuid4().hex}"}).json()["id"]
    response = invoke(v, fields={"project_id": other})
    assert response.json()["status"] == "failed" and not calls
    assert expand(v, response.json()).status_code in (403, 409)


def test_delta_tool_replay_and_agent_observation_fail_closed_after_source_revocation(delta_api, monkeypatch):
    v = delta_api
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Viewer source delta"})
    assert conversation.status_code == 200, conversation.text
    result = completed(invoke(v, headers=v["member_headers"], conversation_id=conversation.json()["id"]))
    assert expand(v, result, headers=v["member_headers"]).status_code == 200
    repository = SourceAccessRepository()
    scope = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], v["before"].binding_id, SourceAccessRule("restricted"),
        expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    calls = []
    monkeypatch.setattr(app.state.container.source_deltas.reader, "read", lambda target: calls.append(target))
    denied = expand(v, result, headers=v["member_headers"])
    assert denied.status_code == 404 and "keep.py" not in denied.text and "content_hash" not in denied.text
    denied = invoke(v, headers=v["member_headers"], conversation_id=conversation.json()["id"])
    assert denied.json()["status"] == "failed" and not calls
    # The same observation use case used by Planner must not trust a stored receipt.
    with actor_scope(UserProfile.model_validate(v["member"])):
        with pytest.raises(KeyError):
            app.state.container.tool_evidence.describe(result["id"], v["project_id"])
    assert not calls


@pytest.mark.parametrize("failure,status,code", [("tamper", 502, "source_delta_integrity_failed"),
    ("offline", 503, "source_delta_unavailable"), ("oversized", 413, "source_delta_page_too_large")])
def test_delta_tool_expansion_sanitizes_archive_errors(delta_api, monkeypatch, failure, status, code):
    v = delta_api
    result = completed(invoke(v))
    if failure == "oversized":
        def fail(*args, **kwargs):
            raise SourceDeltaPageTooLarge("private-storage-secret")
        monkeypatch.setattr(app.state.container.source_deltas, "read", fail)
    else:
        def fail(*args, **kwargs):
            if failure == "tamper":
                return b'{"secret": "private-storage-secret"}'
            raise RuntimeError("private-storage-secret")
        monkeypatch.setattr(app.state.container.source_deltas.reader.archive.storage, "get_bytes", fail)
    denied = expand(v, result)
    assert denied.status_code == status and code in denied.text, denied.text
    assert "private-storage-secret" not in denied.text and "keep.py" not in denied.text
    failed = invoke(v)
    assert failed.json()["status"] == "failed" and "private-storage-secret" not in failed.text


def test_delta_tool_corrupt_receipt_and_request_pins_cannot_be_replayed(delta_api):
    v = delta_api
    result = completed(invoke(v))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        row.result_payload = {**row.result_payload, "image_query": {
            **row.result_payload["image_query"], "result_hash": "sha256:" + "0" * 64}}
    denied = expand(v, result)
    assert denied.status_code == 502 and "keep.py" not in denied.text, denied.text
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        row.result_payload = {**row.result_payload, "image_query": {**result["result"]["image_query"],
            "request": {**result["result"]["image_query"]["request"], "after_revision_id": "missing"}}}
    assert expand(v, result).status_code == 409
