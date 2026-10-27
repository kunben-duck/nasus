"""Resume preparation uses real PG CAS before releasing a non-confirmation gate."""
import asyncio

import pytest
from sqlalchemy import func, select

from apps.api.app.application.agent.agent_models import AgentStep
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.app.infrastructure.agent.resume_checkpoint_commit import SQLAlchemyAgentResumeCommit
from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.agent_resume_fixtures import paused_goal


class RepositoryGraphState:
    def __init__(self):
        self.repository = ConversationRepository()
        self.commits = SQLAlchemyAgentResumeCommit(self.repository)
        self.unconditional_writes = []
        self.events = []
        self.audits = []
        self.fail_after_commit = False

    def get_goal(self, ident):
        return self.repository.get_agent_goal(ident)

    def is_resume_consumed(self, checkpoint):
        return self.commits.is_consumed(checkpoint)

    def persist_goal_at_checkpoint(self, goal, checkpoint):
        self.commits.commit_at_checkpoint(goal, checkpoint)
        if self.fail_after_commit:
            raise RuntimeError("injected failure after nonconfirm resume commit")

    def persist_goal(self, goal):
        self.unconditional_writes.append(goal.model_dump(mode="json"))
        self.repository.upsert_goal(goal)

    def record_goal_audit(self, goal, **details):
        self.audits.append((goal.id, details))

    async def publish_goal_event(self, goal, event, patch):
        self.events.append((goal.id, event, patch))

    async def confirm_tool_invocation(self, ident):
        raise AssertionError("A non-confirmation resume cannot confirm a tool")


def setup_resume(reason):
    goal = paused_goal()
    goal.pause_reason = reason
    step = goal.steps[0]
    step.tool_invocation_id = None if reason == "budget_exhausted" else "inv_missing_source"
    step.tool_input_payload["agent_loop_attempt"] = 2
    goal.steps = [AgentStep(id="think", title="Think", status="completed", phase="thinking"),
                  step, AgentStep(id="decide", title="Decide", status="pending", phase="deciding")]
    goal.steps_completed = 1
    state = RepositoryGraphState()
    state.repository.upsert_goal(goal)
    graph = LocalAgentGraphRuntime(state, AgentGoalStateMachine(), None)
    return goal, state, graph, AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))


def consumption_count(goal):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(AgentResumeConsumptionRecord).where(
            AgentResumeConsumptionRecord.goal_id == goal.id))


@pytest.mark.parametrize("reason", ["budget_exhausted", "missing_source_binding"])
@pytest.mark.parametrize("change", ["budget", "input", "interrupt", "workflow"])
def test_nonconfirm_resume_cannot_overwrite_a_change_after_checkpoint_validation(monkeypatch, reason, change):
    goal, state, graph, checkpoint = setup_resume(reason)
    original = graph.state_machine.start_goal
    concurrent = {}

    def change_before_write(prepared):
        current = state.get_goal(goal.id)
        if change == "budget":
            current.max_steps += 1
        elif change == "input":
            current.steps[1].tool_input_payload["changed_control"] = True
        elif change == "interrupt":
            current.pause_reason = "user_interrupt"
        else:
            current.workflow_id = "different_workflow"
        state.repository.upsert_goal(current)
        concurrent["goal"] = current
        return original(prepared)

    monkeypatch.setattr(graph.state_machine, "start_goal", change_before_write)
    with pytest.raises(AgentResumeCheckpointChanged):
        asyncio.run(graph.prepare_resume(goal.id, expected_resume=checkpoint))
    assert state.get_goal(goal.id) == concurrent["goal"]
    assert consumption_count(goal) == 0
    assert state.unconditional_writes == state.events == state.audits == []


@pytest.mark.parametrize("reason", ["budget_exhausted", "missing_source_binding"])
def test_nonconfirm_resume_commits_the_complete_released_step_once_and_replays_without_confirmation(reason):
    goal, state, graph, checkpoint = setup_resume(reason)
    outcome = asyncio.run(graph.prepare_resume(goal.id, expected_resume=checkpoint))
    saved = state.get_goal(goal.id)
    assert outcome.route == "act" and outcome.step_index == 1
    assert saved.status == "running" and saved.pause_reason is None
    assert saved.steps[1].status == "pending" and saved.steps[1].decision is None
    assert saved.steps[1].tool_invocation_id is None
    assert saved.steps[1].tool_input_payload["agent_loop_attempt"] == (3 if reason == "missing_source_binding" else 2)
    assert consumption_count(goal) == 1 and state.unconditional_writes == []
    assert len(state.audits) == 1 and len(state.events) == 2
    replacement = LocalAgentGraphRuntime(RepositoryGraphState(), AgentGoalStateMachine(), None)
    assert asyncio.run(replacement.prepare_resume(goal.id, expected_resume=checkpoint)) == outcome
    assert state.get_goal(goal.id) == saved and consumption_count(goal) == 1


@pytest.mark.parametrize("reason", ["budget_exhausted", "missing_source_binding"])
def test_nonconfirm_resume_recovers_after_commit_failure_without_resetting_the_attempt(reason):
    goal, state, graph, checkpoint = setup_resume(reason)
    state.fail_after_commit = True
    with pytest.raises(RuntimeError, match="injected failure"):
        asyncio.run(graph.prepare_resume(goal.id, expected_resume=checkpoint))
    saved = state.get_goal(goal.id)
    assert saved.status == "running" and saved.steps[1].status == "pending"
    assert saved.steps[1].tool_invocation_id is None
    assert consumption_count(goal) == 1
    replacement = LocalAgentGraphRuntime(RepositoryGraphState(), AgentGoalStateMachine(), None)
    outcome = asyncio.run(replacement.prepare_resume(goal.id, expected_resume=checkpoint))
    assert outcome.route == "act" and outcome.step_index == 1
    assert state.get_goal(goal.id) == saved and consumption_count(goal) == 1


@pytest.mark.parametrize("reason", ["budget_exhausted", "missing_source_binding"])
def test_legacy_nonconfirm_resume_keeps_the_existing_unpinned_contract(reason):
    goal, state, graph, _ = setup_resume(reason)
    outcome = asyncio.run(graph.prepare_resume(goal.id))
    assert outcome.route == "act" and outcome.step_index == 1
    assert state.get_goal(goal.id).status == "running"
    assert consumption_count(goal) == 0 and state.unconditional_writes


@pytest.mark.parametrize("attempt", ["invalid-attempt", {"invalid": True}])
def test_invalid_source_retry_attempt_does_not_leave_a_partially_running_goal(attempt):
    goal, state, graph, _ = setup_resume("missing_source_binding")
    goal.steps[1].tool_input_payload["agent_loop_attempt"] = attempt
    state.repository.upsert_goal(goal)
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    with pytest.raises((ValueError, TypeError)):
        asyncio.run(graph.prepare_resume(goal.id, expected_resume=checkpoint))
    assert state.get_goal(goal.id) == goal
    assert state.unconditional_writes == state.events == state.audits == []
    assert consumption_count(goal) == 0
