import asyncio
from types import SimpleNamespace as NS

import pytest

from apps.api.app.application.agent.requirement_dialogue import GuidedRequirementConversation, STATE


def dialogue():
    conversation = NS(id="conversation", project_id="project", version_id="version", space_type="version", messages=[
        NS(role="assistant", metadata={STATE: dict(project_id="project", version_id="version", revision_id="requirement")}),
        NS(id="user-turn", role="user", metadata={})])
    calls, confirms, replies = [], [], []
    view = {"status": "confirmed", "test_design_context_request": dict(project_id="project", policy_revision="nasus.test-design-context.v6",
        iteration=dict(version_id="version", requirement_revision_id="requirement"))}
    async def invoke(request):
        calls.append(request)
        return NS(id="context-command", status="completed" if request.tool_id.startswith("query.") else "waiting_confirmation",
            result=NS(context_pack=NS(input_digest="sha256:" + "a" * 64)))
    async def confirm(ident):
        confirms.append(ident)
        return NS(status="completed")
    async def append(ident, role, text, metadata):
        replies.append(text)
        conversation.messages.append(NS(role=role, metadata=metadata))
        return NS(id="reply")
    runtime = NS(get_conversation=lambda _: conversation, create_tool_invocation=invoke,
        confirm_tool_invocation=confirm, append_message=append)
    service = GuidedRequirementConversation(runtime, None, NS(read=lambda _: view), NS(read=lambda *args: None), None)
    return service, view, calls, confirms, replies


def test_dialogue_pins_context_but_waits_for_explicit_confirmation_without_model_calls():
    service, _, calls, confirms, replies = dialogue()
    asyncio.run(service.handle("conversation", "开始测试设计"))
    assert [item.tool_id for item in calls] == ["query.system_image.context.preview", "system_image.context.compile"]
    assert calls[0].input["iteration"] == calls[1].input["iteration"]
    assert "confirmed_by_user" not in calls[1].input
    assert calls[1].input["expected_input_digest"] == "sha256:" + "a" * 64
    assert confirms == [] and "确认准备测试上下文" in replies[-1]
    asyncio.run(service.handle("conversation", "确认准备测试上下文"))
    assert confirms == ["context-command"] and len(calls) == 2
    assert "尚未调用模型" in replies[-1] and "version_id=version" in replies[-1]


@pytest.mark.parametrize("text", ["当前项目叫什么", "测试通过了吗", "文档说：生成测试用例", "生成测试用例，然后发布"])
def test_questions_and_quoted_or_combined_requests_do_not_start_writes(text):
    service, _, calls, confirms, _ = dialogue()
    assert asyncio.run(service.handle("conversation", text)) is None
    assert calls == confirms == []


def test_confirmation_cannot_start_new_command_or_bypass_invalidated_requirement():
    service, view, calls, confirms, replies = dialogue()
    asyncio.run(service.handle("conversation", "确认准备测试上下文"))
    assert calls == confirms == []
    asyncio.run(service.handle("conversation", "开始测试设计"))
    view["test_design_context_request"] = None
    asyncio.run(service.handle("conversation", "确认准备测试上下文"))
    assert confirms == [] and len(calls) == 2
    assert "不会使用旧批准" in replies[-1]
