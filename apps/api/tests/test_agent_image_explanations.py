import pytest
from types import SimpleNamespace

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep
from apps.api.app.application.agent.explanations import AgentGoalExplanationApplicationService
from apps.api.app.application.platform.tool_models import ToolInvocation


def test_image_thinking_explains_independent_investigation_without_legacy_ready_claim():
    from apps.api.app.application.agent.graph import LocalAgentGraphRuntime

    proposal = SimpleNamespace(goal_template="system_image_build")
    reasoning = LocalAgentGraphRuntime._reasoning_for_proposal(proposal)
    assert "source-pinned plan" in reasoning
    assert "Confirm structure and evidence investigation separately" in reasoning
    assert "do not approve business expectations or publish the image" in reasoning
    assert "materialize" not in reasoning and "ready enough" not in reasoning


@pytest.mark.parametrize("reason,waiting,terms", [
    ("missing_captured_code", "source_capture", ("capture", "same goal", "confirm")),
    ("structural_candidate_review", "candidate_review", ("structural candidate", "investigation", "confirm")),
    ("build_plan_phase_prepared", "plan_phase_review", ("new plan", "budget", "confirm")),
    ("build_completion_review", "completion_review", ("gaps", "publication", "approval")),
])
def test_paused_image_goal_explains_the_required_independent_action(reason, waiting, terms):
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project",
        title="Pinned image", status="paused", summary="Saved artifacts",
        goal_template="system_image_build", pause_reason=reason, steps=[])
    assert AgentGoalExplanationApplicationService._waiting_on(goal, None) == waiting
    action = AgentGoalExplanationApplicationService._next_action(goal, None).lower()
    assert all(term in action for term in terms)
    assert "no next action" not in action


@pytest.mark.parametrize("status,waiting", [("completed", "none"), ("failed", "human_review"),
    ("running", "agent_runtime"), ("pending", "agent_runtime")])
def test_old_pause_reason_never_overrides_current_runtime_or_terminal_status(status, waiting):
    goal = AgentGoal(id="goal", conversation_id="conversation", title="Changed state",
        status=status, summary="Current state wins", pause_reason="missing_captured_code", steps=[])
    assert AgentGoalExplanationApplicationService._waiting_on(goal, None) == waiting


@pytest.mark.parametrize("status", ["pending", "running"])
@pytest.mark.parametrize("reason", [None, "missing_captured_code", "structural_candidate_review",
    "missing_source_binding", "budget_exhausted", "user_interrupt"])
@pytest.mark.parametrize("invocation_status", ["waiting_confirmation", "waiting_approval", "cancelled"])
def test_runtime_action_ignores_previous_pause_and_tool_gate(status, reason, invocation_status):
    step_status = "pending" if status == "pending" else "running"
    goal = AgentGoal(id="goal", conversation_id="conversation", title="Current runtime",
        status=status, summary="Historical gates are not current permission", pause_reason=reason,
        steps=[AgentStep(id="work", title="Read fixed evidence", status=step_status, phase="acting")])
    invocation = ToolInvocation(id="old-command", tool_id="system_image.build.authorize",
        status=invocation_status, summary="Previous gate")
    assert AgentGoalExplanationApplicationService._waiting_on(goal, invocation) == "agent_runtime"
    action = AgentGoalExplanationApplicationService._next_action(goal, invocation)
    assert action == ("The next planned step is: Read fixed evidence." if status == "pending" else
        "The Agent is currently working on: Read fixed evidence.")
    assert "old-command" not in action


@pytest.mark.parametrize("status,waiting", [("cancelled", "none"), ("completed", "none"),
    ("failed", "human_review")])
@pytest.mark.parametrize("reason", [None, "missing_captured_code", "budget_exhausted", "user_interrupt"])
@pytest.mark.parametrize("invocation_status", ["waiting_confirmation", "waiting_approval"])
def test_terminal_goal_never_suggests_resuming_or_confirming_old_work(status, waiting, reason, invocation_status):
    goal = AgentGoal(id="goal", conversation_id="conversation", title="Terminal image goal",
        status=status, summary="Original history is retained", pause_reason=reason,
        steps=[AgentStep(id="old-work", title="Old planned work", status="pending", phase="acting")])
    invocation = ToolInvocation(id="old-command", tool_id="system_image.build.authorize",
        status=invocation_status, summary="Historical gate")
    assert AgentGoalExplanationApplicationService._waiting_on(goal, invocation) == waiting
    action = AgentGoalExplanationApplicationService._next_action(goal, invocation).lower()
    assert not any(value in action for value in ("confirm", "approve", "resum", "old-command", "old planned work"))
    if status == "cancelled":
        assert "cancelled" in action and "saved" in action


@pytest.mark.parametrize("invocation_status,waiting,verb", [
    ("waiting_confirmation", "user_confirmation", "Confirm"), ("waiting_approval", "approval", "Approve")])
def test_paused_goal_keeps_its_current_independent_gate(invocation_status, waiting, verb):
    goal = AgentGoal(id="goal", conversation_id="conversation", title="Current gate", status="paused",
        summary="A new independent decision is required", steps=[])
    invocation = ToolInvocation(id="current-command", tool_id="system_image.build.authorize",
        status=invocation_status, summary="Current gate")
    assert AgentGoalExplanationApplicationService._waiting_on(goal, invocation) == waiting
    action = AgentGoalExplanationApplicationService._next_action(goal, invocation)
    assert action.startswith(verb) and "current-command" in action


@pytest.mark.parametrize("status", ["pending", "running"])
@pytest.mark.parametrize("historical_status", ["pending", "running"])
def test_additional_phase_action_does_not_reactivate_historical_steps(status, historical_status):
    current_status = "pending" if status == "pending" else "running"
    goal = AgentGoal(id="goal", conversation_id="conversation", title="Additional phase", status=status,
        summary="Preserve the original steps", target_refs=["build_plan_phase:new-phase"], steps=[
            AgentStep(id="historical", title="Old phase work", status=historical_status, phase="acting"),
            AgentStep(id="build_plan_phase:new-phase", title="New phase marker", status="completed"),
            AgentStep(id="new-work", title="Read the new fixed plan", status=current_status, phase="acting")])
    action = AgentGoalExplanationApplicationService._next_action(goal, None)
    assert action == ("The next planned step is: Read the new fixed plan." if status == "pending" else
        "The Agent is currently working on: Read the new fixed plan.")
    assert goal.steps[0].status == historical_status
