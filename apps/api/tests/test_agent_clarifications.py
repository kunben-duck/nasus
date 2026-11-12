import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.app.application.agent.capability_responses import unavailable_project_action
from apps.api.app.application.agent.messages import ConversationMessageApplicationService
from apps.api.app.application.agent.planner import LLMStructuredAgentPlanner
from apps.api.app.application.agent.planner_clarifications import CLARIFICATION_INSTRUCTIONS
from apps.api.app.domain.agent.memory import AgentMemoryContext
from apps.api.app.domain.agent.runtime_models import DirectAnswer, OrchestratorDecision
from apps.api.tests.test_build_dialogue import dialogue_fixture


def planner_for(payload):
    fallback = OrchestratorDecision(kind="direct_answer", direct_answer=DirectAnswer("No action dispatched."))
    return LLMStructuredAgentPlanner(
        fallback=SimpleNamespace(plan=AsyncMock(return_value=fallback)),
        llm=SimpleNamespace(generate_reply=AsyncMock(return_value=SimpleNamespace(mode="live", content=json.dumps(payload)))),
        tools=[], settings_provider=lambda: SimpleNamespace(runtime_mode="live"), custom_api_key_provider=lambda: "",
        memory_context_builder=AsyncMock(return_value=AgentMemoryContext("policy", "context", "history", 0, 0)),
        allow_deterministic_write_fallback=False,
    )


@pytest.mark.parametrize("nested", [False, True])
def test_planner_preserves_specific_clarifications_in_flat_and_nested_responses(nested):
    details = {"question": "请提供要查询的执行记录 ID。", "reason": "run_selection", "missing_context": ["run_id"]}
    payload = {"kind": "clarification", **({"clarification": details} if nested else details)}
    planner = planner_for(payload)
    result = asyncio.run(planner.plan(SimpleNamespace(id="chat", project_id=None, version_id=None, task_id=None, us_id=None), "查看执行记录"))
    assert result.clarification.question == details["question"]
    assert result.clarification.reason == details["reason"]
    assert result.clarification.missing_context == ["run_id"]
    assert CLARIFICATION_INSTRUCTIONS in planner.llm.generate_reply.await_args.kwargs["system_prompt"]


@pytest.mark.parametrize("details", [{}, {"question": ""}, {"question": "  "}, {"question": {}},
    {"question": "Specific", "missing_context": "project_id"}, {"question": "Specific", "reason": {}}])
def test_malformed_clarifications_use_safe_fallback_instead_of_inventing_missing_context(details):
    planner = planner_for({"kind": "clarification", "clarification": details})
    result = asyncio.run(planner.plan(SimpleNamespace(id="chat", project_id=None, version_id=None, task_id=None, us_id=None), "Help"))
    assert result.kind == "direct_answer" and result.direct_answer.fallback_text == "No action dispatched."


@pytest.mark.parametrize("message", ["删除当前所有的项目", "删除当前所有项目", "把当前的所有项目都删掉", "清空全部项目",
    "请帮我删除当前项目", "确认删除所有项目", "Delete all projects", "Please remove all of my projects."])
def test_project_deletion_explains_missing_capability_without_creating_confirmation(message):
    result = unavailable_project_action(message, {"project.create", "query.answer"})
    assert result.kind == "clarification"
    assert result.clarification.reason == "capability_unavailable:project.delete"
    assert result.clarification.missing_context == []
    expected = "未执行删除" if "项目" in message else "No projects or data were deleted"
    assert expected in result.clarification.question


@pytest.mark.parametrize("message", ["当前项目名称是什么", "帮我构建系统画像", "不要删除所有项目", '解释“删除所有项目”是什么意思',
    '"删除所有项目"', "项目名称是删除所有项目", "delete all project files", "删除项目中的测试用例"])
def test_capability_response_does_not_capture_questions_quotes_names_or_other_objects(message):
    assert unavailable_project_action(message, set()) is None


def test_registered_project_deletion_is_left_to_the_governed_planner():
    assert unavailable_project_action("删除当前所有的项目", {"project.delete"}) is None


@pytest.mark.parametrize("stage", ["name", "sources", "review", "existing", "building"])
def test_unsupported_request_never_becomes_a_project_name_or_resumes_another_goal(stage):
    guide, runtime, conversation, saved, _ = dialogue_fixture(stage)
    service = ConversationMessageApplicationService(runtime)
    service.guided_build = guide
    result = asyncio.run(service.process_message("chat", "删除当前所有的项目"))
    assert result["clarification"]["reason"] == "capability_unavailable:project.delete"
    assert conversation.messages[0].metadata["system_image_intake"] == saved
    runtime.plan_message.assert_not_called()
    runtime.create_tool_invocation.assert_not_called()
    runtime.resume_goal.assert_not_called()
    runtime.confirm_tool_invocation.assert_not_called()
    runtime.append_message.assert_awaited_once()
