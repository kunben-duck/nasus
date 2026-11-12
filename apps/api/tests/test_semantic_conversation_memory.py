import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.app.application.agent.agent_models import ConversationSession, ConversationMessage, MessageBlock, ConversationSummaryCheckpoint
from apps.api.app.application.agent.semantic_memory import SemanticConversationMemory
from apps.api.app.domain.agent.conversation_memory import ConversationHistory, ContextBudget, ContextBudgetExceeded
from apps.api.app.application.agent.memory_models import ConversationDigest, MemoryEntry
from apps.api.app.infrastructure.llm.conversation_token_budget import ConversationTokenCounter
from apps.api.app.infrastructure.llm.gateway import LLMGateway


class Jobs:
    def __init__(self, checkpoints):
        self.rows, self.checkpoints = {}, checkpoints

    def enqueue(self, job):
        return self.rows.setdefault(job["id"], {**job, "status": "pending", "attempts": 0, "reason": ""})

    def get(self, ident):
        return self.rows[ident]

    def latest(self, conversation_id):
        rows = [j for j in self.rows.values() if j["conversation_id"] == conversation_id]
        return rows[-1] if rows else None

    def claim(self, ident):
        job = self.rows[ident]
        if job["status"] != "pending":
            return None
        job["status"], job["attempts"] = "running", job["attempts"] + 1
        return dict(job)

    def fail(self, ident, reason, attempt):
        if self.rows[ident]["attempts"] == attempt:
            self.rows[ident].update(status="failed", reason=reason)

    def commit(self, job, checkpoint):
        parent = self.checkpoints[-1].id if self.checkpoints else None
        if parent != job["parent_id"]:
            self.rows[job["id"]]["status"] = "superseded"
            return False
        self.checkpoints.append(checkpoint)
        self.rows[job["id"]].update(status="completed", checkpoint_id=checkpoint.id)
        return True


class Model:
    """Deterministic fixture, not a substitute for a live-model quality evaluation."""
    def __init__(self):
        self.calls, self.inputs = 0, []
        self.version, self.fail, self.after_call = "one", None, None
        self.input_limit = 16384

    def binding(self):
        return {"digest": self.version}

    def counter(self):
        return ConversationTokenCounter()

    def budget(self):
        return ContextBudget(input_limit=self.input_limit)

    async def summarize(self, payload, binding):
        self.calls += 1
        self.inputs.append(deepcopy(payload))
        if self.fail:
            raise self.fail
        assert binding == self.binding()
        digest = ConversationDigest.model_validate(payload["previous_digest"] or {})
        for message in payload["messages"]:
            if message["role"] != "user":
                continue
            text = message["text"]
            if text.startswith("约束："):
                digest.constraints.append(MemoryEntry(text=text, origin="user_statement", refs=[message["ref"]]))
            elif text.startswith("更正："):
                for entry in digest.decisions:
                    entry.status = "superseded"
                digest.decisions.append(MemoryEntry(text=text, origin="user_statement", refs=[message["ref"]]))
            elif text.startswith("项目："):
                digest.decisions.append(MemoryEntry(text=text, origin="user_statement", refs=[message["ref"]]))
            elif text.startswith("待确认："):
                digest.pending_questions.append(MemoryEntry(text=text, origin="user_statement", refs=[message["ref"]]))
        if not digest.entries():
            digest.objective.append(MemoryEntry(text="Continue the task", origin="user_statement",
                                              refs=[payload["messages"][0]["ref"]]))
        if self.after_call:
            self.after_call(digest)
        return digest, {"mode": "fixture", "input_tokens": 100, "output_tokens": 30}


def fixture():
    conversation = ConversationSession(id="conv-memory", session_id="session", title="Memory", space_type="build", space_id="memory")
    checkpoints, model, scope = [], Model(), {"value": "scope-one"}
    jobs = Jobs(checkpoints)
    async def publish(*args):
        pass
    service = SemanticConversationMemory(jobs=jobs, model=model, conversation=lambda _: conversation,
        checkpoints=lambda: checkpoints, guard=lambda _: scope["value"], publish=publish)
    return service, conversation, model, checkpoints, scope


def add_turn(conversation, text):
    for role, content in (("user", text), ("assistant", "已记录，继续当前任务。")):
        conversation.messages.append(ConversationMessage(id=f"m{len(conversation.messages)}", role=role,
            created_at=(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=len(conversation.messages))).isoformat(),
            status="completed", content_type="text", blocks=[MessageBlock(type="text", text=content)]))


def test_thirty_chinese_turns_three_compactions_preserve_constraints_and_corrections():
    service, conversation, model, checkpoints, _ = fixture()
    for index in range(30):
        text = {0: "约束：仅构建候选，不允许自动发布。", 1: "项目：支付系统，分支 refs/heads/main",
                2: "待确认：是否导入历史用例？", 12: "更正：项目更名支付网关，分支 refs/heads/release"}.get(index, f"继续检查第{index}个模块")
        add_turn(conversation, text)
        if index in {9, 19, 29}:
            asyncio.run(service.compact(conversation))
    assert len(checkpoints) == model.calls == 3
    final = ConversationDigest.model_validate(checkpoints[-1].memory_payload["digest"])
    assert final.constraints[0].text == "约束：仅构建候选，不允许自动发布。"
    assert final.decisions[0].status == "superseded"
    assert "refs/heads/release" in final.decisions[-1].text
    assert final.pending_questions[0].refs == ["message:m4"]
    assert len(service.history(conversation).messages) == 8
    assert len(conversation.messages) == 60
    assert model.inputs[1]["previous_digest"] is not None


def test_background_schedule_never_calls_model_and_keeps_uncovered_history():
    service, conversation, model, checkpoints, _ = fixture()
    for _ in range(12):
        add_turn(conversation, "context " * 150)
    asyncio.run(service.maybe_schedule(conversation))
    assert model.calls == 0 and not checkpoints
    assert service.jobs.rows
    assert len(service.history(conversation).messages) == 24


def test_inspecting_memory_never_enqueues_or_calls_summary_even_over_budget():
    service, conversation, model, _, _ = fixture()
    for _ in range(12):
        add_turn(conversation, "历史上下文" * 300)
    _, metadata = asyncio.run(service.prepare(conversation, "system", "context", inspect_only=True))
    assert metadata["estimated_input_tokens"] > metadata["input_limit"]
    assert model.calls == 0 and not service.jobs.rows


def test_pending_question_keeps_four_complete_turns_in_addition_to_current_input():
    service, conversation, _, _, _ = fixture()
    for _ in range(8):
        add_turn(conversation, "约束：不要自动发布")
    add_turn(conversation, "现在项目名称是什么？")
    conversation.messages.pop()
    asyncio.run(service.compact(conversation))
    assert len(service.history(conversation).messages) == 9


def test_task_notes_keep_current_facts_separate_from_stale_summary_claims():
    import json
    from types import SimpleNamespace
    from apps.api.app.application.agent.task_memory import task_notebook
    from apps.api.app.application.agent.build_dialogue_inputs import BuildIntake, STATE_KEY

    _, conversation, _, _, _ = fixture()
    add_turn(conversation, "先使用已提交的代码，待确认是否需要需求和用例。")
    conversation.messages[-1].metadata[STATE_KEY] = BuildIntake(project_name="Payment", code="/approved/repository").model_dump()
    checkpoint = SimpleNamespace(memory_payload={"digest": {
        "constraints": [{"text": "自动发布", "status": "superseded"}, {"text": "禁止自动发布", "status": "active"}],
        "decisions": [{"text": "模型曾声称已经发布", "status": "active"}],
    }})
    goal = SimpleNamespace(id="goal", status="completed", steps=[])
    notebook = json.loads(task_notebook(conversation, checkpoint, goal,
        {"candidate_status": "ready_for_review", "published": False}).split("\n", 1)[1])
    assert notebook["active_goal"]["status"] == "completed"
    assert notebook["image_read_state"]["published"] is False
    assert notebook["constraints"] == [{"text": "禁止自动发布", "status": "active"}]
    assert notebook["intake"]["code"] == "/approved/repository"
    assert notebook["missing_inputs"] == ["whether_to_include_requirements_and_tests"]
    assert "模型曾声称已经发布" not in str(notebook)


def test_tool_observations_resolve_prefixed_refs_without_copying_large_results():
    from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
    service, conversation, model, _, _ = fixture()
    for _ in range(8):
        add_turn(conversation, "约束：失败后不重复提交")
    conversation.messages[1].tool_refs = ["tool_invocation:tool_failed"]
    conversation.tool_invocations = [ToolInvocation(id="tool_failed", tool_id="system_image.build",
        status="failed", summary="failed", created_at="2026-01-01", initiator_surface="chat",
        result=ToolResult(invocation_id="tool_failed", status="failed", summary="失败日志" * 10000))]
    asyncio.run(service.compact(conversation))
    assert model.inputs[0]["observations"][0]["ref"] == "tool:tool_failed"
    assert model.inputs[0]["observations"][0]["status"] == "failed"
    assert len(model.inputs[0]["observations"][0]["summary"]) == 1000


@pytest.mark.parametrize("fault", ["unknown_ref", "wrong_origin", "scope_change", "model_change"])
def test_invalid_summary_or_changed_authority_is_not_published(fault):
    service, conversation, model, checkpoints, scope = fixture()
    for _ in range(6):
        add_turn(conversation, "Continue")
    def mutate(digest):
        if fault == "unknown_ref":
            digest.objective[0].refs = ["message:invented"]
        elif fault == "wrong_origin":
            digest.objective[0].origin = "tool_observation"
        elif fault == "scope_change":
            scope["value"] = "revoked"
        else:
            model.version = "changed"
    model.after_call = mutate
    job = service.schedule(conversation)
    result = asyncio.run(service.run(job["id"]))
    assert result["status"] == "failed" and not checkpoints
    assert len(conversation.messages) == 12


def test_failure_retains_previous_digest_and_unsummarized_tail():
    service, conversation, model, checkpoints, _ = fixture()
    for _ in range(7):
        add_turn(conversation, "约束：不要发布")
    asyncio.run(service.compact(conversation))
    previous = checkpoints[-1]
    for _ in range(5):
        add_turn(conversation, "继续")
    model.fail = RuntimeError("private provider body")
    with pytest.raises(ContextBudgetExceeded):
        asyncio.run(service.compact(conversation))
    assert checkpoints[-1] is previous
    assert len(service.history(conversation).messages) == 18
    assert service.jobs.latest(conversation.id)["reason"] == "summary_model_unavailable"


def test_legacy_checkpoint_is_rebuilt_from_original_text():
    service, conversation, model, checkpoints, _ = fixture()
    for i in range(7):
        add_turn(conversation, "约束：不要自动发布" if i == 0 else "继续")
    checkpoints.append(ConversationSummaryCheckpoint(id="old", conversation_id=conversation.id,
        summary_text="truncated legacy text", message_range_end="m6", created_at="2020-01-01"))
    asyncio.run(service.compact(conversation))
    assert model.inputs[0]["previous_digest"] is None
    assert model.inputs[0]["messages"][0]["text"] == "约束：不要自动发布"
    assert checkpoints[-1].memory_payload["parent_id"] == "old"


def test_duplicate_job_does_not_generate_twice_and_append_is_preserved():
    service, conversation, model, checkpoints, _ = fixture()
    for _ in range(8):
        add_turn(conversation, "Continue")
    first = service.schedule(conversation)
    assert service.schedule(conversation)["id"] == first["id"]
    add_turn(conversation, "Newer input")
    asyncio.run(service.run(first["id"]))
    asyncio.run(service.run(first["id"]))
    assert model.calls == 1
    assert "Newer input" in str(service.history(conversation))


def test_history_recall_is_current_conversation_scoped_and_paged():
    service, conversation, _, _, _ = fixture()
    add_turn(conversation, "支付 " + "x" * 5000)
    assert service.recall(conversation.id, query="支付")["messages"][0]["next_offset"] == 4000
    assert service.recall(conversation.id, message_id="other-chat-message")["messages"] == []
    service.guard = lambda _: (_ for _ in ()).throw(PermissionError())
    with pytest.raises(PermissionError):
        service.recall(conversation.id, message_id="m0")


def test_provider_roles_and_current_input_are_not_duplicated():
    history = ConversationHistory("Digest", [{"role": "user", "content": "old"},
        {"role": "assistant", "content": "reply"}, {"role": "user", "content": "CURRENT"}])
    messages = LLMGateway._chat_messages("system", "CURRENT", "context", history)
    assert [m["role"] for m in messages] == ["system", "user", "user", "assistant", "user"]
    assert str(messages).count("CURRENT") == 1
    assert LLMGateway._gemini_messages("CURRENT", "context", history)[2]["role"] == "model"
    assert LLMGateway._dialogue_messages("CURRENT", "context", history)[2]["role"] == "assistant"


def test_unknown_model_count_is_conservative_for_chinese_and_enforces_final_budget():
    counter = ConversationTokenCounter("custom-model", "openai_compatible")
    assert counter.count("中文") == 6
    history = ConversationHistory("", [], ContextBudget(input_limit=1000), counter.count)
    with pytest.raises(ContextBudgetExceeded):
        LLMGateway._check_history_budget("system", "中" * 500, "", history)


def test_oversized_current_turn_is_not_silently_removed():
    service, conversation, _, _, _ = fixture()
    add_turn(conversation, "大" * 6000)
    with pytest.raises(ContextBudgetExceeded):
        asyncio.run(service.prepare(conversation, "system", "context"))
    assert len(conversation.messages) == 2


def test_hard_threshold_is_not_a_reason_to_drop_fitting_recent_turns():
    service, conversation, model, _, _ = fixture()
    add_turn(conversation, "x" * 14500)
    history, metadata = asyncio.run(service.prepare(conversation, "system", "context"))
    assert model.budget().hard_limit < metadata["estimated_input_tokens"] <= model.budget().input_limit
    assert len(history.messages) == 2 and model.calls == 0


def test_partial_failed_reply_is_retained_as_non_verified_history():
    service, conversation, _, _, _ = fixture()
    add_turn(conversation, "继续构建")
    conversation.messages[-1].status = "interrupted"
    history = service.history(conversation)
    assert len(history.messages) == 2 and "message_status=interrupted" in history.messages[-1]["content"]
    assert "not verified" in service.recall(conversation.id, message_id="m1")["messages"][0]["text"]
