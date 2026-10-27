"""Chat consent pins one pending command instead of resuming an arbitrary gate."""
import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep, ConversationSession
from apps.api.app.application.agent.messages import ConversationMessageApplicationService
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged


def fixture_runtime(*, pinned=True, standalone=False):
    conversation = ConversationSession(id="conversation_a", session_id="session_a", title="Fixed image",
        space_type="project", space_id="project_a", project_id="project_a")
    tool_id = "system_image.build.investigate" if pinned else "system_image.sources.register"
    invocation = ToolInvocation(id="tool_a1", conversation_id=conversation.id, tool_id=tool_id,
        status="waiting_confirmation", summary="Independent confirmation",
        input_payload={"project_id": "project_a", **({} if standalone else {"agent_goal_id": "goal_a"})})
    goal = AgentGoal(id="goal_a", conversation_id=conversation.id, project_id="project_a", title="Fixed goal",
        status="paused", pause_reason="waiting_confirmation", summary="Pending command", workflow_id="workflow_a",
        target_refs=["image_revision:image_a"] if pinned else [],
        steps=[AgentStep(id="step_a", title="Investigate", phase="acting", status="blocked",
            selected_tool_id=tool_id, tool_invocation_id=invocation.id, tool_input_payload=invocation.input_payload)])
    calls = []

    async def resume(goal_id, **kwargs):
        calls.append(("resume", goal_id, kwargs))
        return goal

    async def confirm(invocation_id):
        calls.append(("confirm", invocation_id))
        return invocation

    runtime = SimpleNamespace(is_confirmation_message=lambda _: True,
        list_tool_invocations=lambda **kwargs: [invocation], get_goal=lambda _: goal,
        get_conversation=lambda _: conversation, resume_goal=resume,
        get_tool_invocation=lambda _: invocation, confirm_tool_invocation=confirm)
    return ConversationMessageApplicationService(runtime), goal, invocation, calls


def test_chat_pins_the_whole_fixed_goal_for_its_exact_pending_command():
    service, goal, invocation, calls = fixture_runtime()
    result = asyncio.run(service.handle_confirmation_message_if_any(goal.conversation_id, f"confirm {invocation.id}"))
    assert result == {"agent_goal": goal, "tool_invocation": invocation}
    expected = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    assert calls == [("resume", goal.id, {"expected_resume": expected})]


@pytest.mark.parametrize("change", ["goal_id", "conversation", "project", "invocation_conversation",
    "invocation_project", "blocked_invocation", "blocked_tool", "duplicate_blocked", "pause_reason", "status"])
def test_chat_never_confirms_a_different_scope_or_gate(change):
    service, goal, invocation, calls = fixture_runtime()
    if change == "goal_id":
        goal.id = "goal_other"
    elif change == "conversation":
        goal.conversation_id = "conversation_other"
    elif change == "project":
        goal.project_id = "project_other"
    elif change == "invocation_conversation":
        invocation.conversation_id = "conversation_other"
    elif change == "invocation_project":
        invocation.input_payload["project_id"] = "project_other"
    elif change == "blocked_invocation":
        goal.steps[0].tool_invocation_id = "tool_b2"
    elif change == "blocked_tool":
        goal.steps[0].selected_tool_id = "system_image.build.structure"
    elif change == "duplicate_blocked":
        goal.steps.append(goal.steps[0].model_copy(update={"id": "step_b"}))
    elif change == "pause_reason":
        goal.pause_reason = "structural_candidate_review"
    else:
        goal.status = "running"
    with pytest.raises(AgentResumeCheckpointChanged):
        asyncio.run(service.handle_confirmation_message_if_any("conversation_a", f"confirm {invocation.id}"))
    assert calls == []


def test_an_explicit_old_command_does_not_select_the_new_pending_command():
    service, goal, _, calls = fixture_runtime()
    assert asyncio.run(service.handle_confirmation_message_if_any(goal.conversation_id, "confirm tool_dead")) is None
    assert calls == []


def test_non_pinned_goal_keeps_the_legacy_one_argument_resume_contract():
    service, goal, _, calls = fixture_runtime(pinned=False)
    asyncio.run(service.handle_confirmation_message_if_any(goal.conversation_id, "confirm"))
    assert calls == [("resume", goal.id, {})]


def test_standalone_command_still_uses_canonical_confirmation():
    service, goal, invocation, calls = fixture_runtime(standalone=True)
    result = asyncio.run(service.handle_confirmation_message_if_any(goal.conversation_id, "confirm"))
    assert result == {"tool_invocation": invocation}
    assert calls == [("confirm", invocation.id)]


def test_chat_precondition_is_not_recaptured_after_a_concurrent_budget_change():
    service, goal, invocation, calls = fixture_runtime()
    expected = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))

    async def changed_before_driver(goal_id, *, expected_resume):
        assert goal_id == goal.id and expected_resume == expected
        goal.max_steps += 1
        expected_resume.require_matches(goal.model_dump(mode="json"))

    service._runtime.resume_goal = changed_before_driver
    with pytest.raises(AgentResumeCheckpointChanged):
        asyncio.run(service.handle_confirmation_message_if_any(goal.conversation_id, f"confirm {invocation.id}"))
    assert calls == []
