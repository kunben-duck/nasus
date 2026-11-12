"""M1 history/source ACL boundaries with real PostgreSQL and SSE outbox replay."""
import asyncio
from uuid import uuid4

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.application.agent.agent_models import ConversationMessage
from apps.api.app.main import app
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_version_delivery_api import publish
from apps.api.tests.test_natural_build_entries_api import send


def prepare(v, *, create):
    head = publish(v)
    membership = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "qa_lead"})
    assert membership.status_code == 200, membership.text
    selected = send(v, "create iteration HistoryProbe using publication " + head["publication_id"], headers=v["member_headers"])
    done = send(v, "confirm iteration creation", headers=v["member_headers"]) if create else selected
    return selected, done


def set_access(v, *, allowed):
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id,
        SourceAccessRule("project" if allowed else "restricted"), expected_epoch=snapshot.acl_epoch,
        changed_by=v["owner"]["id"], invocation_id="history-acl-" + uuid4().hex)


def forbid_image_reads(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("M1 history authorization must not read an image artifact or rebuild delivery")
    runtime = get_runtime_assembly()
    monkeypatch.setattr(runtime.image_revisions, "frozen_header", unexpected)
    monkeypatch.setattr(runtime.image_revisions, "frozen_snapshot", unexpected)
    monkeypatch.setattr(runtime.version_delivery, "read", unexpected)


@pytest.mark.parametrize("created", [False, True])
def test_delivery_http_history_rechecks_source_acl_without_image_reads(publication, monkeypatch, created):
    v = publication
    selected, done = prepare(v, create=created)
    url = "/v1/conversations/" + done["id"]
    headers = v["member_headers"]
    clean = v["client"].post("/v1/conversations", headers=headers, json={"space_type": "knowledge",
        "space_id": "merge-" + uuid4().hex, "project_id": v["project_id"], "title": "Empty merge target"})
    assert clean.status_code == 200, clean.text
    clean_url = "/v1/conversations/" + clean.json()["id"]
    forbid_image_reads(monkeypatch)
    assert v["client"].get(url, headers=headers).json()["messages"] == done["messages"]
    assert v["client"].get(url + "/messages", headers=headers).json() == done["messages"]
    assert any(item["id"] == done["id"] for item in v["client"].get("/v1/conversations",
        headers=headers, params={"project_id": v["project_id"]}).json())
    set_access(v, allowed=False)
    for path in (url, url + "/messages", url + "/messages?before_message_id=" + selected["messages"][0]["id"],
            url + "/events"):
        response = v["client"].get(path, headers=headers)
        assert response.status_code == 403, response.text
        assert "HistoryProbe" not in response.text and "image_binding" not in response.text
    assert all(item["id"] != done["id"] for item in v["client"].get("/v1/conversations",
        headers=headers, params={"project_id": v["project_id"]}).json())
    found = v["client"].get("/v1/conversations/search", headers=headers, params={"q": "HistoryProbe"})
    assert found.status_code == 200 and not found.json()["conversations"] and not found.json()["message_hits"]
    ensured = v["client"].post("/v1/conversations", headers=headers,
        json={"space_type": "project", "space_id": v["project_id"], "title": "Reload"})
    assert ensured.status_code == 403, ensured.text
    for source_url, target_id in ((url, clean.json()["id"]), (clean_url, done["id"])):
        merged = v["client"].post(source_url + "/merge", headers=headers, json={"target_conversation_id": target_id})
        assert merged.status_code == 403, merged.text
    assert v["client"].get(clean_url, headers=headers).json() == clean.json()
    # Current source administrators still have access; no history is destroyed.
    assert v["client"].get(url, headers=v["headers"]).status_code == 200
    set_access(v, allowed=True)
    assert v["client"].get(url, headers=headers).json()["messages"] == done["messages"]


def test_open_delivery_stream_and_reconnect_recheck_live_acl(publication, monkeypatch):
    v = publication
    selected, done = prepare(v, create=True)
    selected_id, done_id = selected["messages"][-1]["id"], done["messages"][-1]["id"]
    cid = done["id"]
    runtime = get_runtime_assembly()
    asyncio.run(runtime.platform_events.push_event(cid, "history.safe.marker", "conversation", cid,
        "patch", {}, [["conversation", cid]]))
    forbid_image_reads(monkeypatch)

    async def until_marker(stream):
        messages = []
        async for event in stream:
            if event and event.event_type == "history.safe.marker":
                return messages
            if event and event.payload.get("message"):
                messages.append(event.payload["message"])
        pytest.fail("missing durable stream marker")

    async def observe():
        with actor_scope(UserProfile.model_validate(v["member"])):
            stream = app.state.container.agent.stream_conversation_events(cid)
            try:
                async for event in stream:
                    if event and event.payload.get("message_id") == selected_id:
                        cursor = event.event_id
                        assert "delivery_intake" in event.payload["message"]["metadata"]
                        break
                set_access(v, allowed=False)
                remaining = await until_marker(stream)
                assert all(item["id"] != done_id for item in remaining)
                assert not any("version_delivery" in item["metadata"] or "delivery_intake" in item["metadata"] for item in remaining)
            finally:
                await stream.aclose()
            replay = app.state.container.agent.stream_conversation_events(cid, cursor)
            try:
                assert all(item["id"] != done_id for item in await until_marker(replay))
            finally:
                await replay.aclose()
            set_access(v, allowed=True)
            restored = app.state.container.agent.stream_conversation_events(cid, cursor)
            try:
                messages = await until_marker(restored)
                assert next(item for item in messages if item["id"] == done_id)["metadata"] == done["messages"][-1]["metadata"]
            finally:
                await restored.aclose()

    async def bounded():
        await asyncio.wait_for(observe(), timeout=10)
    asyncio.run(bounded())


def test_delivery_history_tools_and_legacy_summary_recheck_source_acl(publication, monkeypatch):
    v = publication
    _, done = prepare(v, create=True)
    headers, cid = v["member_headers"], done["id"]
    runtime = get_runtime_assembly()
    monkeypatch.setattr(runtime.agent_memory, "semantic", None)
    checkpoint = v["client"].post("/v1/agent-memory/checkpoints", headers=headers,
        json={"conversation_id": cid})
    assert checkpoint.status_code == 200 and "HistoryProbe" in checkpoint.json()["summary_text"], checkpoint.text
    private_space = "private-delivery-" + uuid4().hex
    private = v["client"].post("/v1/conversations", headers=headers, json={"space_type": "build",
        "space_id": private_space, "project_id": v["project_id"], "title": "Private delivery"})
    assert private.status_code == 200, private.text
    private_message = ConversationMessage.model_validate({**done["messages"][-1], "id": uuid4().hex})
    ConversationRepository().append_message(private.json()["id"], private_message)
    # The project/source administrator is still not the private Build chat owner.
    private_summary = v["client"].post("/v1/agent-memory/checkpoints", headers=v["headers"],
        json={"space_ref": "build:" + private_space})
    assert private_summary.status_code == 403, private_summary.text
    receipts = []
    for tool, arguments in (("search", {"query": "HistoryProbe"}),
            ("read", {"message_id": done["messages"][-1]["id"]})):
        payload = {"conversation_id": cid, "tool_id": "query.conversation.history." + tool,
            "input": {"conversation_id": cid, **arguments}, "idempotency_key": uuid4().hex}
        response = v["client"].post("/v1/tool-invocations", headers=headers, json=payload)
        assert response.status_code == 200 and response.json()["status"] == "completed", response.text
        assert response.json()["result"]["conversation_history"]["messages"]
        receipts.append((response.json()["id"], payload))
    set_access(v, allowed=False)
    for receipt_id, payload in receipts:
        receipt = v["client"].get("/v1/tool-invocations/" + receipt_id, headers=headers)
        assert receipt.status_code == 403, receipt.text
        replay = v["client"].post("/v1/tool-invocations", headers=headers, json=payload)
        assert replay.status_code == 403, replay.text
    for selector in ({"space_ref": "project:" + v["project_id"]}, {"conversation_id": cid}):
        summary = v["client"].post("/v1/agent-memory/checkpoints", headers=headers, json=selector)
        assert summary.status_code == 403 and "HistoryProbe" not in summary.text, summary.text
        context = v["client"].get("/v1/agent-memory/context", headers=headers, params=selector)
        assert context.status_code == 403 and "HistoryProbe" not in context.text, context.text
