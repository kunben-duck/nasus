from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import time

import pytest
from sqlalchemy import func, select, update

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.code_index_lifecycle import CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL, CODE_INDEX_CANCEL_TOOL
from apps.api.app.domain.system_image.code_index_generation import CodeIndexLeaseLost
from apps.api.app.domain.system_image.source_access import SourceAccessRule, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord, CodeIndexWorkerLeaseRecord
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.db_models import ConversationRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_code_index_generations import pg_index, opened
from apps.api.tests.test_code_graph_enrichment import _adapter, _config, _fake_codebase_memory, _FixtureProcessRunner
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm


def install_native(v, monkeypatch, tmp_path, runner=None):
    from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
    from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
    extraction = app.state.container.structure_builds.preparation.extraction
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    native = _adapter(_config(binary, mode="required"))
    if runner is not None:
        native._process_runner = runner
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    adapter = RegisteredCodeIntelligenceAdapter(CompositeCodeIntelligenceAdapter(
        TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations)
    monkeypatch.setattr(extraction, "_source_code_intelligence", adapter)
    return native, log


def generation(invocation):
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).where(CodeIndexGenerationRecord.invocation_id == invocation)).all()
        assert len(rows) == 1
        return CodeIndexGenerationRepository._pin(rows[0])


def url(v, pin):
    return f"/v1/projects/{v['project_id']}/system-image/code-indexes/{pin.generation_id}"


def tool(v, tool_id, payload, headers=None, **coordination):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": tool_id, "input": {"project_id": v["project_id"], **payload}, **coordination})
    assert response.status_code == 200, response.text
    return response.json()


def cancel(v, pin):
    command = tool(v, CODE_INDEX_CANCEL_TOOL, {"generation_id": pin.generation_id, "expected_generation_hash": pin.content_hash})
    assert command["status"] == "waiting_confirmation", command
    with session_scope() as session:
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state not in {"cancel_requested", "cancelled"}
    return confirm(v, command["id"])


def test_http_status_and_agent_tools_are_current_metadata_without_provider_access(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    _, log = install_native(v, monkeypatch, tmp_path)
    invocation = submit(v, request(v))
    assert confirm(v, invocation)["status"] == "completed"
    pin = generation(invocation)
    calls = log.read_text()
    response = v["client"].get(url(v, pin), headers=v["headers"])
    assert response.status_code == 200, response.text
    status = response.json()["status"]
    assert response.json()["can_cancel"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert status["state"] == "idle" and status["worker_state"] == "none" and status["epoch"] == 1
    assert status["invocation_status"] == "completed" and status["protocol"] is not None
    assert "owner_id" not in response.text and "local-object://" not in response.text and str(tmp_path) not in response.text
    listed = tool(v, CODE_INDEX_LIST_TOOL, {"binding_id": pin.binding_id, "limit": 1})
    assert listed["status"] == "completed" and listed["result"]["code_index"]["items"][0]["generation_id"] == pin.generation_id
    queried = tool(v, CODE_INDEX_STATUS_TOOL, {"generation_id": pin.generation_id})
    assert queried["status"] == "completed", queried
    saved_status = queried["result"]["code_index"]["status"]
    assert {key: value for key, value in saved_status.items() if key != "observed_at"} == {key: value for key, value in status.items() if key != "observed_at"}
    with actor_scope(UserProfile.model_validate(v["owner"])):
        described = app.state.container.tool_evidence.describe(queried["id"], v["project_id"])
    assert described["code_index"]["status"]["pin"]["content_hash"] == pin.content_hash
    assert log.read_text() == calls


def test_status_checks_project_source_acl_and_late_revocation(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    install_native(v, monkeypatch, tmp_path)
    invocation = submit(v, request(v))
    assert confirm(v, invocation)["status"] == "completed"
    pin = generation(invocation)
    assert v["client"].get(url(v, pin)).status_code == 401
    assert v["client"].get(url(v, pin), headers=v["member_headers"]).status_code == 403
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    assert v["client"].get(url(v, pin), headers=v["member_headers"]).status_code == 200
    assert v["client"].get(url(v, pin), headers=v["member_headers"]).json()["can_cancel"] is False
    application = app.state.container.code_index_lifecycle
    original = application.repository.status
    def revoke(selected):
        value = original(selected)
        repo = SourceAccessRepository()
        snapshot = repo.load_snapshot(v["project_id"])
        repo.set_policy(v["project_id"], pin.binding_id, SourceAccessRule("restricted", ()),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="lifecycle-revocation")
        return value
    monkeypatch.setattr(application.repository, "status", revoke)
    denied = v["client"].get(url(v, pin), headers=v["member_headers"])
    assert denied.status_code == 409 and "provider_fingerprint" not in denied.text, denied.text
    monkeypatch.setattr(application.repository, "status", original)
    assert v["client"].get(url(v, pin), headers=v["member_headers"]).status_code == 403
    listing = url(v, pin).rsplit("/", 1)[0]
    assert v["client"].get(listing, headers=v["member_headers"], params={"binding_id": pin.binding_id}).status_code == 403


def test_canonical_cancel_stops_running_structure_and_retains_durable_pin(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    paused, release = Event(), Event()
    class PauseAfterNativeIndex(_FixtureProcessRunner):
        def run(self, args, **kwargs):
            result = super().run(args, **kwargs)
            if len(args) > 2 and args[2] == "index_repository":
                paused.set()
                deadline = time.monotonic() + 15
                while not release.wait(.02):
                    kwargs["check_current"]()
                    if time.monotonic() > deadline:
                        raise TimeoutError("test worker was not released")
            return result
    install_native(v, monkeypatch, tmp_path, PauseAfterNativeIndex())
    invocation = submit(v, request(v))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(confirm, v, invocation)
        try:
            assert paused.wait(10), "native index did not reach the held phase"
            pin = generation(invocation)
            read = v["client"].get(url(v, pin), headers=v["headers"])
            assert read.status_code == 200 and read.json()["status"]["worker_state"] == "active", read.text
            cancelled = cancel(v, pin)
            assert cancelled["status"] == "completed", cancelled
            assert cancelled["result"]["code_index"]["outcome"] == "cancel_requested"
            result = pending.result(timeout=10)
            assert result["status"] == "cancelled", result
        finally:
            release.set()
    assert v["client"].get(url(v, pin), headers=v["headers"]).json()["status"]["state"] == "cancelled"
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None
        assert session.get(CodeIndexGenerationRecord, pin.generation_id).content_hash == pin.content_hash
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == pin.generation_id,
            SSEEventOutboxRecord.event_type == "system_image.code_index.cancel_requested")).all()
        assert len(events) == 1 and events[0].event_payload["tool_invocation_id"] == cancelled["id"]


def test_cancel_between_index_release_and_candidate_commit_blocks_commit(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    install_native(v, monkeypatch, tmp_path)
    invocation = submit(v, request(v))
    artifacts = app.state.container.structure_builds.preparation.candidates.artifacts
    original = artifacts.put
    cancellation = []
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"]))
    def before_commit(*args, **kwargs):
        value = original(*args, **kwargs)
        pin = generation(invocation)
        cancellation.append(cancel(v, pin))
        return value
    monkeypatch.setattr(artifacts, "put", before_commit)
    result = confirm(v, invocation)
    assert cancellation[0]["status"] == "completed", cancellation
    assert cancellation[0]["result"]["code_index"]["outcome"] == "cancelled"
    assert result["status"] == "cancelled", result
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == before


def test_cancel_after_candidate_commit_does_not_change_generation_or_original_command(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    install_native(v, monkeypatch, tmp_path)
    invocation = submit(v, request(v))
    original = confirm(v, invocation)
    assert original["status"] == "completed", original
    pin = generation(invocation)
    cancelled = cancel(v, pin)
    assert cancelled["status"] == "completed" and cancelled["result"]["code_index"]["outcome"] == "already_committed", cancelled
    assert confirm(v, invocation) == original
    with session_scope() as session:
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "idle"
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == pin.generation_id,
            SSEEventOutboxRecord.event_type.in_(("system_image.code_index.cancel_requested", "system_image.code_index.cancelled")))) == 0


def test_status_observation_rechecks_expired_lease_without_renewing_or_starting_provider(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    _, log = install_native(v, monkeypatch, tmp_path)
    invocation = submit(v, request(v))
    assert confirm(v, invocation)["status"] == "completed"
    pin = generation(invocation)
    with session_scope() as session:
        session.get(ToolInvocationRecord, invocation).status = "running"
    CodeIndexGenerationRepository().claim(pin, owner_id="not-a-live-process")
    saved = tool(v, CODE_INDEX_STATUS_TOOL, {"generation_id": pin.generation_id})
    assert saved["result"]["code_index"]["status"]["worker_state"] == "active", saved
    with session_scope() as session:
        session.execute(update(CodeIndexWorkerLeaseRecord).where(CodeIndexWorkerLeaseRecord.generation_id == pin.generation_id)
            .values(lease_until=func.clock_timestamp() - timedelta(seconds=1)))
    calls = log.read_text()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        described = app.state.container.tool_evidence.describe(saved["id"], v["project_id"])
    assert described["code_index"]["status"]["worker_state"] == "expired", described
    assert log.read_text() == calls
    with session_scope() as session:
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).lease_until < session.scalar(select(func.clock_timestamp()))


def test_revoked_source_blocks_saved_tool_audit_and_idempotent_replay_without_mutating_history(evidence_api, monkeypatch, tmp_path):
    from uuid import uuid4
    v = evidence_api
    _, log = install_native(v, monkeypatch, tmp_path)
    invocation = submit(v, request(v))
    assert confirm(v, invocation)["status"] == "completed"
    pin = generation(invocation)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    replay_key = uuid4().hex
    payload = {"tool_id": CODE_INDEX_STATUS_TOOL, "conversation_id": v["conversation"].json()["id"],
        "idempotency_key": replay_key, "input": {"project_id": v["project_id"], "generation_id": pin.generation_id}}
    response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["result"]["code_index"]["status"]["pin"]["content_hash"] == pin.content_hash
    history_url = f"/v1/tool-invocations/{saved['id']}"
    assert v["client"].get(history_url, headers=v["member_headers"]).status_code == 200
    assert v["client"].get("/v1/audit-events", headers=v["member_headers"], params={"tool_invocation_id": saved["id"]}).json()
    with session_scope() as session:
        before = session.get(ToolInvocationRecord, saved["id"]).result_payload
    repo = SourceAccessRepository()
    repo.set_policy(v["project_id"], pin.binding_id, SourceAccessRule("restricted", ()),
        expected_epoch=repo.load_snapshot(v["project_id"]).acl_epoch,
        changed_by=v["owner"]["id"], invocation_id="private-lifecycle-history")
    calls = log.read_text()
    for method, path in (("get", history_url), ("post", history_url + "/confirm")):
        denied = getattr(v["client"], method)(path, headers=v["member_headers"])
        assert denied.status_code == 403 and "provider_fingerprint" not in denied.text, denied.text
    listed = v["client"].get("/v1/tool-invocations", headers=v["member_headers"], params={"tool_id": CODE_INDEX_STATUS_TOOL})
    assert listed.status_code == 200 and saved["id"] not in {item["id"] for item in listed.json()}
    assert v["client"].get("/v1/audit-events", headers=v["member_headers"], params={"tool_invocation_id": saved["id"]}).json() == []
    replayed = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=payload)
    assert replayed.status_code == 403 and "provider_fingerprint" not in replayed.text, replayed.text
    assert v["client"].get(history_url, headers=v["headers"]).json()["result"] == saved["result"]
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, saved["id"]).result_payload == before
        assert session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(
            ToolInvocationRecord.tool_id == CODE_INDEX_STATUS_TOOL, ToolInvocationRecord.idempotency_key == replay_key)) == 1
    assert log.read_text() == calls


def test_missing_project_conversations_do_not_break_lists_search_or_expose_history(evidence_api):
    from uuid import uuid4

    v = evidence_api
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    visible = v["client"].get(f"/v1/conversations/{v['conversation'].json()['id']}", headers=v["headers"])
    assert visible.status_code == 200, visible.text
    visible = visible.json()
    missing_project_id = "missing_project_" + uuid4().hex
    orphan_ids = []
    with session_scope() as session:
        for actor in (v["owner"], v["member"]):
            orphan_id = "orphan_conversation_" + uuid4().hex
            orphan_ids.append(orphan_id)
            session.add(ConversationRecord(
                id=orphan_id, session_id="orphan_session_" + uuid4().hex,
                title=visible["title"] + " private orphan history", space_type="project",
                space_id=missing_project_id, project_id=missing_project_id, initiator_id=actor["id"],
            ))
    for headers in (v["headers"], v["member_headers"]):
        for params in ({}, {"q": visible["title"]}, {"status": visible["status"]}):
            response = v["client"].get("/v1/conversations", headers=headers, params=params)
            assert response.status_code == 200, response.text
            assert v["conversation"].json()["id"] in {item["id"] for item in response.json()}
            assert not set(orphan_ids) & {item["id"] for item in response.json()}
            assert missing_project_id not in response.text and "private orphan history" not in response.text
        filtered = v["client"].get("/v1/conversations", headers=headers, params={"project_id": missing_project_id})
        assert filtered.status_code == 200 and filtered.json() == [], filtered.text
        searched = v["client"].get("/v1/conversations/search", headers=headers, params={"q": visible["title"]})
        assert searched.status_code == 200, searched.text
        assert missing_project_id not in searched.text and "private orphan history" not in searched.text
        for orphan_id in orphan_ids:
            for suffix in ("", "/messages", "/events"):
                response = v["client"].get(f"/v1/conversations/{orphan_id}{suffix}", headers=headers)
                assert response.status_code == 404, response.text
    with session_scope() as session:
        assert all(session.get(ConversationRecord, orphan_id) is not None for orphan_id in orphan_ids)


def test_project_shared_conversation_and_outbox_only_broadcast_lifecycle_status(evidence_api, monkeypatch, tmp_path):
    import asyncio
    from uuid import uuid4
    from apps.api.app.application.platform.tool_models import EventPayload
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    v = evidence_api
    install_native(v, monkeypatch, tmp_path)
    original = submit(v, request(v))
    assert confirm(v, original)["status"] == "completed"
    pin = generation(original)
    conversation_id = v["conversation"].json()["id"]
    saved = tool(v, CODE_INDEX_STATUS_TOOL, {"generation_id": pin.generation_id}, conversation_id=conversation_id)
    with session_scope() as session:
        rows = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == saved["id"], SSEEventOutboxRecord.event_type == "tool.invocation.updated")).all()
        assert rows
        for row in rows:
            projected = row.event_payload["payload"]["tool_invocation"]
            assert projected["status"] == "completed" and projected["input_payload"] == {} and projected["result"] is None
            assert "provider_fingerprint" not in str(row.event_payload) and pin.generation_id not in str(row.event_payload)
        event = EventPayload.model_validate(rows[0].event_payload)
    # Replaying an older full receipt must not rewrite the stored event or expose it.
    historical = event.model_copy(update={"event_id": "evt_" + uuid4().hex, "payload": {"tool_invocation": saved}})
    EventOutboxRepository().append(historical)
    events = app.state.container.agent._events
    async def replay():
        stream = events.stream_conversation_events(conversation_id, event.event_id)
        try:
            while True:
                item = await asyncio.wait_for(stream.__anext__(), timeout=5)
                if item is not None and item.event_id == historical.event_id:
                    return [item]
        finally:
            await stream.aclose()
    replayed = asyncio.run(replay())
    assert replayed[0].event_id == historical.event_id and replayed[0].entity_version == historical.entity_version
    assert replayed[0].payload["tool_invocation"]["result"] is None
    assert historical.payload["tool_invocation"]["result"] == saved["result"]
    with session_scope() as session:
        stored = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == historical.event_id))
        assert stored.event_payload["payload"]["tool_invocation"]["result"] == saved["result"]
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    repo = SourceAccessRepository()
    repo.set_policy(v["project_id"], pin.binding_id, SourceAccessRule("restricted", ()),
        expected_epoch=repo.load_snapshot(v["project_id"]).acl_epoch,
        changed_by=v["owner"]["id"], invocation_id="private-conversation-index")
    for path in (f"/v1/conversations/{conversation_id}", "/v1/conversations"):
        response = v["client"].get(path, headers=v["member_headers"])
        assert response.status_code == 200, response.text
        items = response.json() if isinstance(response.json(), list) else [response.json()]
        projected = next(item for session in items for item in session["tool_invocations"] if item["id"] == saved["id"])
        assert projected["result"] is None and projected["input_payload"] == {}
    assert v["client"].get(f"/v1/tool-invocations/{saved['id']}", headers=v["headers"]).json()["result"] == saved["result"]


def test_discovery_paginates_exact_binding_and_cross_project_status_does_not_open_provider(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    _, log = install_native(v, monkeypatch, tmp_path)
    pins = []
    for _ in range(3):
        original = submit(v, request(v))
        assert confirm(v, original)["status"] == "completed"
        pins.append(generation(original))
    endpoint = url(v, pins[0]).rsplit("/", 1)[0]
    seen, after = [], ""
    before = log.read_text()
    for _ in range(3):
        response = v["client"].get(endpoint, headers=v["headers"], params={
            "binding_id": pins[0].binding_id, "limit": 1, "after_id": after})
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) == 1
        seen.extend(item["generation_id"] for item in page["items"])
        after = page["next_after_id"]
    assert after is None and seen == sorted(pin.generation_id for pin in pins)
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Other lifecycle scope"}).json()["id"]
    foreign = v["client"].get(url(v, pins[0]).replace(v["project_id"], other), headers=v["headers"])
    assert foreign.status_code == 404 and "provider_fingerprint" not in foreign.text
    assert v["client"].get(endpoint, headers=v["headers"], params={"binding_id": pins[0].binding_id, "limit": 31}).status_code == 422
    assert log.read_text() == before


@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_readers_cannot_confirm_cancellation_and_client_consent_is_not_trusted(evidence_api, monkeypatch, tmp_path, role):
    v = evidence_api
    install_native(v, monkeypatch, tmp_path)
    original = submit(v, request(v))
    assert confirm(v, original)["status"] == "completed"
    pin = generation(original)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": role}).status_code == 200
    assert v["client"].get(url(v, pin), headers=v["member_headers"]).status_code == 200
    payload = {"generation_id": pin.generation_id, "expected_generation_hash": pin.content_hash}
    unconfirmed = tool(v, CODE_INDEX_CANCEL_TOOL, {**payload, "confirmed_by_user": True,
        "confirmed_actor_id": v["owner"]["id"], "confirmed_at": "2026-10-07T00:00:00+00:00"})
    assert unconfirmed["status"] == "waiting_confirmation" and "confirmed_by_user" not in unconfirmed["input_payload"]
    denied = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json={
        "tool_id": CODE_INDEX_CANCEL_TOOL, "input": {"project_id": v["project_id"], **payload}})
    assert denied.status_code == 403, denied.text
    denied_confirmation = v["client"].post(f"/v1/tool-invocations/{unconfirmed['id']}/confirm", headers=v["member_headers"])
    assert denied_confirmation.status_code == 403, denied_confirmation.text
    pending = v["client"].get(f"/v1/tool-invocations/{unconfirmed['id']}", headers=v["headers"])
    assert pending.status_code == 200 and pending.json() == unconfirmed
    assert confirm(v, unconfirmed["id"])["result"]["code_index"]["outcome"] == "already_committed"
    with session_scope() as session:
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "idle"
        assert session.get(StructureBuildArtifactRecord, original) is not None


def test_repeat_cancel_requests_do_not_repeat_outbox_or_replace_generation(pg_index):
    from uuid import uuid4
    v = pg_index
    with opened(v) as index:
        pin = index.generation
        for _ in range(2):
            command_id = uuid4().hex
            with session_scope() as session:
                session.add(ToolInvocationRecord(id=command_id, tool_id=CODE_INDEX_CANCEL_TOOL, status="running",
                    summary="independently confirmed test", input_payload={"project_id": pin.project_id,
                        "generation_id": pin.generation_id, "expected_generation_hash": pin.content_hash, "confirmed_by_user": True}))
            outcome, status = v["repository"].cancel_confirmed(pin, invocation_id=command_id, require_current=lambda: None)
            assert outcome == "cancel_requested" and status.pin == pin
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
                SSEEventOutboxRecord.entity_id == pin.generation_id,
                SSEEventOutboxRecord.event_type == "system_image.code_index.cancel_requested")) == 1


def test_cancel_outbox_and_late_authorization_failure_roll_back_lease(pg_index, monkeypatch):
    from uuid import uuid4
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    v = pg_index
    with opened(v) as index:
        pin = index.generation
        cancel_id = uuid4().hex
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=cancel_id, tool_id=CODE_INDEX_CANCEL_TOOL, status="running", summary="confirmed cancellation test",
                input_payload={"project_id": pin.project_id, "generation_id": pin.generation_id,
                    "expected_generation_hash": pin.content_hash, "confirmed_by_user": True}))
        original = EventOutboxRepository.append
        def fail(self, event, **kwargs):
            if event.event_type == "system_image.code_index.cancel_requested":
                raise RuntimeError("atomic outbox failure")
            return original(self, event, **kwargs)
        monkeypatch.setattr(EventOutboxRepository, "append", fail)
        with pytest.raises(RuntimeError, match="atomic outbox"):
            v["repository"].cancel_confirmed(pin, invocation_id=cancel_id, require_current=lambda: None)
        monkeypatch.setattr(EventOutboxRepository, "append", original)
        checks = []
        def reject_late():
            checks.append(True)
            if len(checks) == 2:
                raise StaleSourceAccessScope("late cancellation revocation")
        with pytest.raises(StaleSourceAccessScope):
            v["repository"].cancel_confirmed(pin, invocation_id=cancel_id, require_current=reject_late)
        with session_scope() as session:
            assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "ready"
            assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
                SSEEventOutboxRecord.entity_id == pin.generation_id,
                SSEEventOutboxRecord.event_type == "system_image.code_index.cancel_requested")) == 0
