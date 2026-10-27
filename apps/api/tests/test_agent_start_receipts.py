"""Durable starts must not steal controllers or turn retries into confirmations."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from apps.api.app.domain.agent.goal_creation import (
    ActiveAgentGoalExists, AgentGoalStartIdentity, AgentGoalStartReplayed, AgentGoalStartRecoveryRequired,
)
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal
from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.agent.loop import AgentLoopRuntime
from apps.api.tests.agent_resume_fixtures import paused_goal
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import AgentGoalWorkflowActivityService
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway


def test_start_conflict_returns_identity_only_instead_of_retrying_the_activity():
    async def start(**kwargs):
        raise ActiveAgentGoalExists("original_goal")

    application = SimpleNamespace(start_goal=start)
    worker = AgentGoalWorkflowActivityService(activity_application_provider=lambda: application)
    result = asyncio.run(worker.start_agent_goal({"conversation_id": "conversation", "workflow_id": "loser_workflow",
        "proposal": {"goal_template": "system_image_build", "title": "Build", "summary": "Original inputs",
            "goal_description": "Build without granting execution"}}))
    assert result == {"_start_error": "active_agent_goal_exists", "goal_id": "original_goal"}


def test_gateway_preserves_typed_start_conflict_for_lifecycle_scope_validation():
    with pytest.raises(ActiveAgentGoalExists) as conflict:
        TemporalClientWorkflowGateway._goal_from_payload(
            {"_start_error": "active_agent_goal_exists", "goal_id": "original_goal"}, "loser_workflow")
    assert conflict.value.goal_id == "original_goal"


def test_a_start_error_cursor_must_never_wait_for_or_accept_resume_signals():
    workflow = NasusAgentGoalWorkflow()
    workflow._current_goal = {"_start_error": "active_agent_goal_exists", "goal_id": "original_goal", "status": "paused"}
    assert not workflow._is_waiting_for_resume(workflow._current_goal)
    asyncio.run(workflow.resume_goal({"goal_id": "original_goal"}))
    assert not workflow._resume_requested


@pytest.mark.parametrize("status", ["paused", "blocked", "completed", "failed", "cancelled"])
def test_replayed_start_reads_the_original_controller_without_graph_audit_or_confirmation(status):
    goal = paused_goal()
    goal.status = status
    state = SimpleNamespace(get_conversation=lambda _: SimpleNamespace(project_id=goal.project_id, us_id=None),
        get_goal=lambda _: goal, create_goal=Mock(side_effect=AgentGoalStartReplayed(goal.id)),
        record_goal_audit=Mock(), publish_goal_proposed=AsyncMock(), append_assistant_message=AsyncMock())
    graph = SimpleNamespace(graph_kind="local", steps_for_proposal=lambda _: [], start=AsyncMock())
    proposal = AgentGoalProposal(goal_template="system_image_build", title="Build", summary="Pinned inputs",
        goal_description="Independent gates", kickoff_message="Only the initial creation may publish this")
    result = asyncio.run(AgentLoopRuntime(state, graph).start_goal(goal.conversation_id, proposal, workflow_id=goal.workflow_id))
    assert result is goal
    identity = state.create_goal.call_args.kwargs["start_identity"]
    assert identity.workflow_id == goal.workflow_id
    graph.start.assert_not_awaited()
    state.record_goal_audit.assert_not_called()
    state.publish_goal_proposed.assert_not_awaited()
    state.append_assistant_message.assert_not_awaited()


@pytest.mark.parametrize("status", ["pending", "running", "draft"])
def test_an_inflight_start_receipt_is_not_permission_to_restart_tool_execution(status):
    goal = paused_goal()
    goal.status = status
    state = SimpleNamespace(get_conversation=lambda _: SimpleNamespace(project_id=goal.project_id, us_id=None),
        get_goal=lambda _: goal, create_goal=Mock(side_effect=AgentGoalStartReplayed(goal.id)))
    graph = SimpleNamespace(graph_kind="local", steps_for_proposal=lambda _: [], start=AsyncMock())
    proposal = AgentGoalProposal(goal_template="system_image_build", title="Build", summary="Pinned inputs", goal_description="Independent gates")
    with pytest.raises(AgentGoalStartRecoveryRequired) as recovery:
        asyncio.run(AgentLoopRuntime(state, graph).start_goal(goal.conversation_id, proposal, workflow_id=goal.workflow_id))
    assert recovery.value.goal_id == goal.id
    graph.start.assert_not_awaited()


def test_activity_must_not_overwrite_a_goal_returned_from_another_workflow():
    goal = paused_goal()
    runtime = SimpleNamespace(start_goal=AsyncMock(return_value=goal))
    projector = SimpleNamespace(upsert_in_conversation=Mock())
    service = AgentWorkflowActivityApplicationService(loop_runtime=runtime, goal_projector=projector)
    with pytest.raises(AgentPlanPolicyViolation) as changed:
        asyncio.run(service.start_goal(conversation_id=goal.conversation_id, proposal=None, workflow_id="another_workflow"))
    assert changed.value.code == "agent_start_scope_changed"
    assert goal.workflow_id != "another_workflow"
    projector.upsert_in_conversation.assert_not_called()


def test_start_digest_is_order_independent_and_changed_inputs_cannot_reuse_it():
    identity = AgentGoalStartIdentity.capture("workflow", {"target": "original", "budget": 0})
    assert identity == AgentGoalStartIdentity.capture("workflow", {"budget": 0, "target": "original"})
    receipt = identity.receipt("goal", "conversation", "project")
    assert "target" not in repr(receipt) and "budget" not in repr(receipt)
    for request in ({"target": "changed", "budget": 0}, {"target": "original", "budget": 1}):
        with pytest.raises(AgentPlanPolicyViolation) as changed:
            AgentGoalStartIdentity.capture("workflow", request).require_receipt(receipt, "conversation", "project")
        assert changed.value.code == "agent_start_scope_changed"


@pytest.mark.parametrize("change", ["goal_id", "project_id", "conversation_id", "workflow_id", "receipt_hash", "schema_version"])
def test_receipt_tampering_is_rejected(change):
    identity = AgentGoalStartIdentity.capture("workflow", {})
    receipt = identity.receipt("goal", "conversation", "project")
    with pytest.raises(AgentPlanPolicyViolation):
        identity.require_receipt({**receipt, change: "changed"}, "conversation", "project")


def test_gateway_observes_start_conflict_without_waiting_for_a_goal_or_projecting_it():
    async def factory(_):
        return SimpleNamespace(start_workflow=AsyncMock(return_value=SimpleNamespace(query=AsyncMock(
            return_value={"_start_error": "active_agent_goal_exists", "goal_id": "original_goal"}))))

    sink = Mock()
    gateway = TemporalClientWorkflowGateway(client_factory=factory, goal_state_sink=sink)
    proposal = AgentGoalProposal(goal_template="system_image_build", title="Build", summary="Inputs", goal_description="Original")
    with pytest.raises(ActiveAgentGoalExists):
        asyncio.run(gateway.start_goal("conversation", proposal))
    sink.assert_not_called()
