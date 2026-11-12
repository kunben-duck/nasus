"""Feature-enabled HTTP and ToolInvocation contracts on disposable PostgreSQL."""
from uuid import uuid4
import asyncio

from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_conversation_memory import Model, add_turn
from apps.api.app.main import app
from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.infrastructure.workflow.conversation_memory_runtime import execute_memory_job
from apps.api.app.infrastructure.persistence.db_models import UserIdentityRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def install_memory(v, monkeypatch):
    service = app.state.container.conversation_memory
    manager = app.state.container.agent._memory
    model = Model()
    monkeypatch.setattr(service, "model", model)
    monkeypatch.setattr(manager, "semantic", service)
    monkeypatch.setattr(manager, "history_recall", service.recall)
    response = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "build", "space_id": "memory-" + uuid4().hex, "title": "Memory test"})
    assert response.status_code == 200, response.text
    conversation = ConversationSession.model_validate(response.json())
    for index in range(12):
        add_turn(conversation, "约束：保留 main 分支，不要自动发布" if index == 0 else f"检查模块 {index}")
    repository = ConversationRepository()
    for message in conversation.messages:
        message.id = uuid4().hex
        repository.append_message(conversation.id, message)
    return conversation, service, model


def test_memory_inspection_checkpoint_and_history_read_are_authorized(evidence_api, monkeypatch):
    v = evidence_api
    conversation, service, model = install_memory(v, monkeypatch)
    url = "/v1/agent-memory/context"
    result = v["client"].get(url, headers=v["headers"], params={"conversation_id": conversation.id})
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "private, no-store"
    assert result.json()["context_budget"]["input_limit"] == 16384
    assert model.calls == 0 and service.jobs.latest(conversation.id) is None
    assert "不要自动发布" not in result.text
    checkpoint = v["client"].post("/v1/agent-memory/checkpoints", headers=v["headers"],
        json={"conversation_id": conversation.id})
    assert checkpoint.status_code == 200, checkpoint.text
    assert checkpoint.json()["memory_payload"]["format_version"] == 2 and model.calls == 1
    assert "不要自动发布" in checkpoint.json()["summary_text"]
    assert v["client"].get(url, headers=v["member_headers"], params={"conversation_id": conversation.id}).status_code == 403

    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": conversation.id, "tool_id": "query.conversation.history.search",
        "input": {"conversation_id": conversation.id, "query": "main"}})
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "completed", receipt
    assert receipt["result"]["conversation_history"]["messages"][0]["message_id"] == conversation.messages[0].id
    read = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": conversation.id, "tool_id": "query.conversation.history.read",
        "input": {"conversation_id": conversation.id, "message_id": conversation.messages[0].id}})
    assert read.status_code == 200 and read.json()["status"] == "completed", read.text
    denied = v["client"].get(f"/v1/tool-invocations/{receipt['id']}", headers=v["member_headers"])
    assert denied.status_code == 403, denied.text


def test_manual_failed_summary_keeps_history_and_returns_real_failure(evidence_api, monkeypatch):
    v = evidence_api
    conversation, service, model = install_memory(v, monkeypatch)
    model.fail = RuntimeError("private provider detail must not leak")
    failed = v["client"].post("/v1/agent-memory/checkpoints", headers=v["headers"],
        json={"conversation_id": conversation.id})
    assert failed.status_code == 400, failed.text
    assert "private provider" not in failed.text
    assert service.jobs.latest(conversation.id)["status"] == "failed"
    original = v["client"].get(f"/v1/conversations/{conversation.id}", headers=v["headers"])
    assert len(original.json()["messages"]) == 24
    assert original.json()["latest_summary_checkpoint_id"] is None


def test_context_recheck_denial_is_forbidden_not_internal_error(evidence_api, monkeypatch):
    v = evidence_api
    conversation, service, _ = install_memory(v, monkeypatch)
    def deny(_conversation):
        raise PermissionError("private revoked identity detail")
    monkeypatch.setattr(service, "guard", deny)
    response = v["client"].get("/v1/agent-memory/context", headers=v["headers"],
        params={"conversation_id": conversation.id})
    assert response.status_code == 403
    assert "private revoked" not in response.text


def test_worker_refreshes_actor_and_persists_real_checkpoint(evidence_api, monkeypatch):
    v = evidence_api
    conversation, service, model = install_memory(v, monkeypatch)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        job = service.schedule(conversation)
    result = asyncio.run(execute_memory_job(service, job["id"]))
    assert result["status"] == "completed" and model.calls == 1, result["reason"]
    assert ConversationRepository().get_conversation(conversation.id).latest_summary_checkpoint_id == result["checkpoint_id"]


def test_worker_never_summarizes_after_account_is_disabled(evidence_api, monkeypatch):
    v = evidence_api
    conversation, service, model = install_memory(v, monkeypatch)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        job = service.schedule(conversation)
    with session_scope() as session:
        session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
    result = asyncio.run(execute_memory_job(service, job["id"]))
    assert result["status"] == "failed" and result["reason"] == "actor_unavailable"
    assert model.calls == 0


def test_worker_discards_summary_if_account_is_disabled_during_generation(evidence_api, monkeypatch):
    v = evidence_api
    conversation, service, model = install_memory(v, monkeypatch)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        job = service.schedule(conversation)
    original = model.summarize

    async def revoke_after_generation(payload, binding):
        result = await original(payload, binding)
        with session_scope() as session:
            session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
        return result

    monkeypatch.setattr(model, "summarize", revoke_after_generation)
    result = asyncio.run(execute_memory_job(service, job["id"]))
    assert result["status"] == "failed" and result["reason"] == "memory_scope_changed"
    assert model.calls == 1
    assert ConversationRepository().get_conversation(conversation.id).latest_summary_checkpoint_id is None


def test_message_post_only_enqueues_compaction_without_waiting_for_summary(evidence_api, monkeypatch):
    from apps.api.app.store import get_runtime_assembly
    v = evidence_api
    conversation, service, model = install_memory(v, monkeypatch)
    model.input_limit = 2048
    runtime = get_runtime_assembly()
    monkeypatch.setattr(runtime.conversation_summary_checkpoints_app, "semantic", service)
    class QueueOnly:
        async def start_turn(self, request):
            return "queued-memory-contract-" + request.turn_id
    monkeypatch.setattr(app.state.container.conversation_turns, "_workflow_runtime", QueueOnly())
    posted = v["client"].post(f"/v1/conversations/{conversation.id}/messages", headers={**v["headers"],
        "Idempotency-Key": uuid4().hex}, json={"content": "继续检查，但不要发布。" * 100})
    assert posted.status_code == 202, posted.text
    assert posted.json()["status"] == "accepted" and model.calls == 0
    assert service.jobs.latest(conversation.id)["status"] == "pending"
