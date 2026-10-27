"""Canonical fixed-image reads use real ToolRuntime, auth, PG and archived inputs."""
from uuid import uuid4
import json

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.domain.system_image.image_revision import ImageRevisionPageTooLarge
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_image_revision_api import selected
from apps.api.tests.test_source_access_api import grant_member, policy


PREFIX = "query.system_image.revisions."


def invoke(v, operation, payload, *, headers=None, key=None, conversation_id=None):
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": PREFIX + operation, "conversation_id": conversation_id or v["conversation"].json()["id"],
        "input": {"project_id": v["project_id"], **payload}, "idempotency_key": key,
        "initiator_surface": "agent_loop", "initiator_actor": "agent",
    })


def pins(v):
    _, summary, _ = selected(v)
    return {"image_revision_id": summary["image_revision_id"], "object_id": v["obj"]["id"],
            "evidence_id": v["evidence"]["evidence_id"]}


def completed(response):
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.text
    assert response.json()["result"]["image_query"]["schema_version"] == "nasus.image-query.v1"
    return response.json()


def expansion(v, result, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{result['id']}/image-query", headers=headers or v["headers"])


def test_revision_tool_list_pages_evidence_and_durable_body_free_receipts(evidence_api):
    v = evidence_api
    identifiers = pins(v)
    catalog = v["client"].get("/v1/tools/catalog", headers=v["headers"]).json()
    assert {PREFIX + op for op in ("list", "read", "evidence")} <= {item["tool_id"] for item in catalog}
    listed = completed(invoke(v, "list", {}))
    assert listed["result"]["image_query"]["revision_ids"] == [identifiers["image_revision_id"]]
    old_list = expansion(v, listed)
    assert old_list.status_code == 200, old_list.text
    assert old_list.json()["items"][0]["image_revision_id"] == identifiers["image_revision_id"]
    results = [listed]
    for section in ("objects", "members", "relationships", "source_members"):
        offset, all_ids = 0, []
        while offset is not None:
            result = completed(invoke(v, "read", {"image_revision_id": identifiers["image_revision_id"],
                                                  "section": section, "offset": offset, "limit": 1}))
            receipt = result["result"]["image_query"]
            page = expansion(v, result)
            assert page.status_code == 200, page.text
            assert page.headers["cache-control"] == "private, no-store"
            assert page.json()["revision"]["publication"] == "blocked_pending_revision_governance"
            if section == "members":
                assert receipt["frozen_members"] == page.json()["items"]
            else:
                assert receipt["frozen_members"] == []
            all_ids.extend(receipt["item_ids"])
            offset = receipt["next_offset"]
            results.append(result)
        assert len(all_ids) == receipt["total"] and len(set(all_ids)) == len(all_ids)
    key = uuid4().hex
    result = completed(invoke(v, "evidence", {**identifiers, "max_lines": 1}, key=key))
    results.append(result)
    assert completed(invoke(v, "evidence", {**identifiers, "max_lines": 1}, key=key))["id"] == result["id"]
    assert invoke(v, "evidence", {**identifiers, "max_lines": 2}, key=key).status_code == 409
    page = expansion(v, result)
    assert page.status_code == 200 and page.json()["content"] == "class Orders:\n", page.text
    assert page.json()["next_start_line"] == 2
    assert page.json()["evidence"]["source_revision_id"] == v["revision"]
    next_result = completed(invoke(v, "evidence", {**identifiers, "start_line": 2}))
    assert "return 'original'" in expansion(v, next_result).json()["content"]
    assert next_result["result"]["next_recommended_tools"] == []

    for item in results:
        with session_scope() as session:
            record = session.get(ToolInvocationRecord, item["id"])
            assert record.result_payload["image_query"] == item["result"]["image_query"]
            events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == item["id"])).all()
            assert events
            persisted = json.dumps(record.result_payload) + json.dumps([event.event_payload for event in events])
        for forbidden in ("class Orders", "return 'original'", "orders.py", "local-object://", "s3://"):
            assert forbidden not in persisted and forbidden not in json.dumps(item)
        audit = v["client"].get("/v1/audit-events", headers=v["headers"], params={"tool_invocation_id": item["id"]})
        assert audit.status_code == 200 and "tool.invocation.completed" in audit.text
        assert "class Orders" not in audit.text

    # A later capture never changes an existing receipt, including list results.
    v["path"].write_text("class Changed:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["path"].unlink()
    assert expansion(v, listed).json() == old_list.json()
    assert expansion(v, result).json() == page.json()
    assert len(completed(invoke(v, "list", {}))["result"]["image_query"]["revision_ids"]) == 2
    empty = completed(invoke(v, "list", {"after_id": "zzzz"}))
    assert empty["result"]["image_query"]["revision_ids"] == []
    assert empty["result"]["next_recommended_tools"] == []


def test_revision_tools_reject_invalid_or_foreign_pins_before_evidence_read(evidence_api, monkeypatch):
    v = evidence_api
    identifiers = pins(v)
    reads = []
    monkeypatch.setattr(app.state.container.image_revisions.evidence, "read", lambda *a, **kw: reads.append(a))
    for op, bad in (("list", {"limit": True}), ("list", {"after_id": 1}),
                    ("read", {"offset": "0"}), ("read", {"section": "latest"}),
                    ("read", {"limit": 101}), ("read", {"file_path": "/etc/passwd"}),
                    ("evidence", {"max_lines": 0}), ("evidence", {"max_lines": 201}),
                    ("evidence", {"max_lines": 1.5}), ("evidence", {"start_line": True}),
                    ("evidence", {"object_id": "missing"}), ("evidence", {"evidence_id": "provider-id"}),
                    ("evidence", {"image_revision_id": "missing"})):
        base = identifiers if op == "evidence" else {"image_revision_id": identifiers["image_revision_id"]} if op == "read" else {}
        response = invoke(v, op, {**base, **bad})
        assert response.status_code == 200 and response.json()["status"] == "failed", response.text
        assert response.json()["result"]["image_query"] is None
    assert not reads
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Other {uuid4().hex}"}).json()
    response = invoke(v, "evidence", {**identifiers, "project_id": other["id"]})
    assert response.json()["status"] == "failed", response.text
    conversation = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "project", "space_id": other["id"], "title": "Other context",
    }).json()
    response = invoke(v, "evidence", identifiers, conversation_id=conversation["id"])
    assert response.json()["status"] == "failed" and not reads, response.text
    assert expansion(v, response.json()).status_code == 403
    failed = invoke(v, "read", {"image_revision_id": "missing"})
    assert expansion(v, failed.json()).status_code == 409


def test_revision_tool_replay_and_observation_fail_closed_after_revocation(evidence_api, monkeypatch):
    v = evidence_api
    identifiers = pins(v)
    grant_member(v)
    policy(v, (v["member"]["id"],))
    results = [completed(invoke(v, "list", {}, headers=v["member_headers"])),
               completed(invoke(v, "read", {"image_revision_id": identifiers["image_revision_id"]}, headers=v["member_headers"])),
               completed(invoke(v, "evidence", identifiers, headers=v["member_headers"]))]
    policy(v)
    calls = []
    original = app.state.container.image_revisions.artifacts.read

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(app.state.container.image_revisions.artifacts, "read", counted)
    for item in results:
        denied = expansion(v, item, v["member_headers"])
        assert denied.status_code == 403 and "Orders" not in denied.text, denied.text
    assert not calls
    response = invoke(v, "evidence", identifiers, headers=v["member_headers"])
    assert response.json()["status"] == "failed" and not calls
    policy(v, (v["member"]["id"],))

    def revoke(*args):
        payload = original(*args)
        policy(v)
        return payload

    monkeypatch.setattr(app.state.container.image_revisions.artifacts, "read", revoke)
    denied = expansion(v, results[-1], v["member_headers"])
    assert denied.status_code in (403, 409) and "Orders" not in denied.text


def test_revision_observation_rejects_corrupt_receipt_and_unavailable_archive(evidence_api, monkeypatch):
    v = evidence_api
    identifiers = pins(v)
    result = completed(invoke(v, "evidence", identifiers))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        row.result_payload = {**row.result_payload, "image_query": {
            **row.result_payload["image_query"], "result_hash": "sha256:" + "0" * 64,
        }}
    denied = expansion(v, result)
    assert denied.status_code == 502 and "original" not in denied.text, denied.text
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, result["id"])
        row.result_payload = {**row.result_payload, "image_query": {**result["result"]["image_query"],
            "request": {**result["result"]["image_query"]["request"], "object_id": "wrong"}}}
    assert expansion(v, result).status_code == 409
    result = completed(invoke(v, "read", {"image_revision_id": identifiers["image_revision_id"]}))
    monkeypatch.setattr(app.state.container.image_revisions.artifacts, "read", lambda *args: {"secret": "provider-error-content"})
    denied = expansion(v, result)
    assert denied.status_code == 502 and "provider-error-content" not in denied.text, denied.text
    failed = invoke(v, "read", {"image_revision_id": identifiers["image_revision_id"]})
    assert failed.json()["status"] == "failed" and "provider-error-content" not in failed.text
    assert v["client"].get(f"/v1/tool-invocations/{result['id']}/image-query").status_code == 401


def test_image_page_error_is_not_misreported_as_an_evidence_line_error(evidence_api, monkeypatch):
    v = evidence_api
    identifiers = pins(v)
    result = completed(invoke(v, "read", {"image_revision_id": identifiers["image_revision_id"]}))

    def oversized(*args, **kwargs):
        raise ImageRevisionPageTooLarge("private provider size details")

    monkeypatch.setattr(app.state.container.image_revisions, "read", oversized)
    response = expansion(v, result)
    assert response.status_code == 413 and "image_page_too_large" in response.text, response.text
    assert "private provider size details" not in response.text
