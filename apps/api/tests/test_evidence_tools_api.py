"""Canonical evidence tool/runtime tests in a disposable PostgreSQL database."""
from __future__ import annotations

from uuid import uuid4
import json

from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api


LIST_TOOL = "query.system_image.evidence.list"
READ_TOOL = "query.system_image.evidence.read"


def invoke(v, tool=READ_TOOL, *, headers=None, updates=None, key=None, conversation_id=None):
    payload = {"project_id": v["project_id"], "source_revision_id": v["revision"]}
    if tool == READ_TOOL:
        payload.update(evidence_id=v["evidence"]["evidence_id"], max_lines=1)
    else:
        payload.update(object_id=v["obj"]["id"], entity_revision_id=v["obj"]["code_reference"]["entity_revision_id"])
    payload.update(updates or {})
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "conversation_id": conversation_id, "tool_id": tool, "input": payload, "idempotency_key": key,
        "initiator_surface": "agent_loop", "initiator_actor": "agent",
    })
    return response


def test_tools_preserve_pins_receipts_audit_and_authorized_expansion(evidence_api):
    v = evidence_api
    client, headers = v["client"], v["headers"]
    catalog = client.get("/v1/tools/catalog", headers=headers).json()
    assert {LIST_TOOL, READ_TOOL} <= {item["tool_id"] for item in catalog}
    listed = invoke(v, LIST_TOOL)
    assert listed.status_code == 200, listed.text
    assert listed.json()["status"] == "completed", listed.text
    assert listed.json()["result"]["evidence_query"]["items"] == v["listed"].json()

    key = uuid4().hex
    conversation_id = v["conversation"].json()["id"]
    result = invoke(v, key=key, conversation_id=conversation_id)
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    body = result.json()
    receipt = body["result"]["evidence_query"]
    assert receipt["evidence"]["source_revision_id"] == v["revision"]
    assert receipt["start_line"] == 1 and receipt["end_line"] == 1
    assert receipt["next_start_line"] == 2
    assert body["result"]["evidence_refs"] == [v["evidence"]["evidence_id"]]
    assert "class Orders" not in result.text and '"object_ref":' not in result.text and "local-object://" not in result.text
    repeated = invoke(v, key=key, conversation_id=conversation_id)
    assert repeated.json()["id"] == body["id"]
    assert repeated.json()["result"]["evidence_query"] == receipt
    assert invoke(v, key=key, updates={"max_lines": 2}, conversation_id=conversation_id).status_code == 409
    persisted = client.get(f"/v1/tool-invocations/{body['id']}", headers=headers)
    assert persisted.json()["result"]["evidence_query"] == receipt
    audit = client.get("/v1/audit-events", headers=headers, params={"tool_invocation_id": body["id"]})
    assert audit.status_code == 200, audit.text
    assert "tool.invocation.completed" in audit.text
    assert "class Orders" not in audit.text and "return 'original'" not in audit.text
    with session_scope() as session:
        stored = session.get(ToolInvocationRecord, body["id"])
        assert stored.result_payload["evidence_query"] == receipt
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == body["id"])).all()
        assert events
        serialized = json.dumps([item.event_payload for item in events])
        assert "class Orders" not in serialized and "return 'original'" not in serialized

    url = f"/v1/tool-invocations/{body['id']}/evidence"
    page = client.get(url, headers=headers)
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "private, no-store"
    assert page.json()["content"] == "class Orders:\n"
    v["path"].unlink()
    assert client.get(url, headers=headers).json() == page.json()
    assert client.get(f"/v1/tool-invocations/{listed.json()['id']}/evidence", headers=headers).status_code == 409


def test_evidence_tools_reject_wrong_scope_bounds_and_provider_inputs(evidence_api, monkeypatch):
    v = evidence_api
    reader = app.state.container.evidence.reader
    calls = []
    original = reader.read

    def counted(target):
        calls.append(target)
        return original(target)

    monkeypatch.setattr(reader, "read", counted)
    for update in ({"source_revision_id": "missing"}, {"source_revision_id": None}, {"max_lines": True},
                   {"max_lines": 201}, {"start_line": 0}, {"file_path": "/etc/passwd"}, {"evidence_id": "provider:123"}):
        result = invoke(v, updates=update)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
        assert result.json()["result"]["evidence_query"] is None
    assert not calls

    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Separate {uuid4().hex}"}).json()
    result = invoke(v, updates={"project_id": other["id"]})
    assert result.json()["status"] == "failed", result.text
    assert not calls
    other_conversation = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "project", "space_id": other["id"], "title": "Different visibility",
    }).json()
    result = invoke(v, conversation_id=other_conversation["id"])
    assert result.json()["status"] == "failed", result.text
    assert not calls


def test_evidence_tool_membership_revocation_blocks_reads_replays_and_expansion(evidence_api, monkeypatch):
    v = evidence_api
    client, member_headers = v["client"], v["member_headers"]
    reader = app.state.container.evidence.reader
    original, reads = reader.read, []
    def counted(target):
        reads.append(target)
        return original(target)
    monkeypatch.setattr(reader, "read", counted)
    denied = invoke(v, headers=member_headers)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "tool_invocation_access_denied"
    assert not reads and "class Orders" not in denied.text and "evidence_query" not in denied.text
    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert client.put(membership_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    key = uuid4().hex
    result = invoke(v, headers=member_headers, key=key)
    assert result.json()["status"] == "completed", result.text
    url = f"/v1/tool-invocations/{result.json()['id']}/evidence"
    assert client.get(url, headers=member_headers).status_code == 200
    assert client.delete(membership_url, headers=v["headers"]).status_code == 200
    assert client.get(url, headers=member_headers).status_code == 403
    assert invoke(v, headers=member_headers, key=key).status_code == 403
    assert client.get(url).status_code == 401
    # Revocation must not overwrite the historical receipt visible to the owner.
    assert client.get(url, headers=v["headers"]).status_code == 200


def test_evidence_expansion_rechecks_storage_and_revocation_during_read(evidence_api, monkeypatch):
    v = evidence_api
    client, headers = v["client"], v["headers"]
    result = invoke(v)
    assert result.json()["status"] == "completed", result.text
    url = f"/v1/tool-invocations/{result.json()['id']}/evidence"
    reader = app.state.container.evidence.reader
    original = reader.read

    monkeypatch.setattr(reader, "read", lambda target: b"tampered")
    assert client.get(url, headers=headers).status_code == 502
    failed = invoke(v)
    assert failed.json()["status"] == "failed" and "integrity" in failed.text, failed.text
    assert "tampered" not in failed.text

    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert client.put(membership_url, headers=headers, json={"role": "viewer"}).status_code == 200

    def revoke(target):
        content = original(target)
        assert client.delete(membership_url, headers=headers).status_code == 200
        return content

    monkeypatch.setattr(reader, "read", revoke)
    page = client.get(url, headers=v["member_headers"])
    assert page.status_code == 403 and "class Orders" not in page.text, page.text
