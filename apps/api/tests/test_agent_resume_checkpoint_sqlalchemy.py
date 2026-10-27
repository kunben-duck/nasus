from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import delete, event

from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from apps.api.app.infrastructure.agent.resume_checkpoint_commit import SQLAlchemyAgentResumeCommit
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.database import SessionLocal
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.agent_resume_fixtures import paused_goal, resume_transition


@pytest.fixture
def saved_goal():
    goal = paused_goal()
    ConversationRepository().upsert_goal(goal)
    try:
        yield goal
    finally:
        # Consumed goals are append-only history. The disposable PG database,
        # not a test DELETE, owns their cleanup.
        if not ConversationRepository().is_resume_consumed(AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))):
            with session_scope() as session:
                session.execute(delete(AgentGoalRecord).where(AgentGoalRecord.id == goal.id))


def test_pg_resume_condition_and_whole_goal_commit_survive_repository_reconstruction(saved_goal):
    checkpoint = AgentResumeCheckpoint.capture(saved_goal.model_dump(mode="json"))
    prepared = resume_transition(saved_goal)
    prepared.steps.append(prepared.steps[0].model_copy(update={"id": "next_step", "tool_invocation_id": None}))
    SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(prepared, checkpoint)
    assert ConversationRepository().get_agent_goal(saved_goal.id) == prepared
    assert SQLAlchemyAgentResumeCommit(ConversationRepository()).is_consumed(checkpoint)
    with pytest.raises(AgentResumeCheckpointChanged):
        SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(prepared, checkpoint)
    assert ConversationRepository().get_agent_goal(saved_goal.id) == prepared


def test_pg_concurrent_resume_has_exactly_one_winner(saved_goal):
    checkpoint = AgentResumeCheckpoint.capture(saved_goal.model_dump(mode="json"))
    barrier = Barrier(2)

    def attempt(index):
        prepared = resume_transition(saved_goal, summary=f"Prepared by {index}")
        barrier.wait(timeout=10)
        try:
            SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(prepared, checkpoint)
            return "committed", prepared
        except AgentResumeCheckpointChanged:
            return "stale", prepared

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    assert sorted(result[0] for result in results) == ["committed", "stale"]
    winner = next(goal for status, goal in results if status == "committed")
    assert ConversationRepository().get_agent_goal(saved_goal.id) == winner


@pytest.mark.parametrize("field,value", [
    ("pause_reason", "structural_candidate_review"), ("status", "cancelled"), ("max_steps", 51),
    ("project_id", "foreign"), ("conversation_id", "foreign"), ("workflow_id", "foreign"),
])
def test_pg_changed_checkpoint_cannot_be_overwritten_by_a_prepared_resume(saved_goal, field, value):
    checkpoint = AgentResumeCheckpoint.capture(saved_goal.model_dump(mode="json"))
    current = saved_goal.model_copy(deep=True)
    setattr(current, field, value)
    ConversationRepository().upsert_goal(current)
    with pytest.raises(AgentResumeCheckpointChanged):
        SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(resume_transition(saved_goal), checkpoint)
    assert ConversationRepository().get_agent_goal(saved_goal.id) == current


@pytest.mark.parametrize("field", ["id", "project_id", "conversation_id", "workflow_id"])
def test_pg_resume_cannot_move_the_aggregate_to_a_different_scope(saved_goal, field):
    checkpoint = AgentResumeCheckpoint.capture(saved_goal.model_dump(mode="json"))
    prepared = resume_transition(saved_goal)
    setattr(prepared, field, "foreign")
    with pytest.raises(AgentResumeCheckpointChanged):
        SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(prepared, checkpoint)
    assert ConversationRepository().get_agent_goal(saved_goal.id) == saved_goal


def test_pg_deleted_goal_is_not_recreated_by_resume():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    with pytest.raises(AgentResumeCheckpointChanged):
        SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(resume_transition(goal), checkpoint)
    assert ConversationRepository().get_agent_goal(goal.id) is None


def test_pg_failed_resume_commit_rolls_back_steps_and_preserves_the_original_checkpoint(saved_goal):
    checkpoint = AgentResumeCheckpoint.capture(saved_goal.model_dump(mode="json"))
    prepared = resume_transition(saved_goal)

    def reject_flush(session, *args):
        if any(isinstance(row, AgentGoalRecord) and row.id == saved_goal.id for row in session.dirty):
            raise RuntimeError("injected resume commit failure")

    event.listen(SessionLocal, "before_flush", reject_flush)
    try:
        with pytest.raises(RuntimeError, match="injected resume commit failure"):
            SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(prepared, checkpoint)
    finally:
        event.remove(SessionLocal, "before_flush", reject_flush)
    unchanged = ConversationRepository().get_agent_goal(saved_goal.id)
    assert unchanged == saved_goal
    assert not SQLAlchemyAgentResumeCommit(ConversationRepository()).is_consumed(checkpoint)
    checkpoint.require_matches(unchanged.model_dump(mode="json"))
    SQLAlchemyAgentResumeCommit(ConversationRepository()).commit_at_checkpoint(prepared, checkpoint)
    assert ConversationRepository().get_agent_goal(saved_goal.id) == prepared


def test_consumption_prevents_aba_recommit_of_a_restored_paused_snapshot(saved_goal):
    checkpoint = AgentResumeCheckpoint.capture(saved_goal.model_dump(mode="json"))
    prepared = resume_transition(saved_goal)
    repository = ConversationRepository()
    repository.upsert_goal(prepared, expected_resume=checkpoint)
    repository.upsert_goal(saved_goal)
    with pytest.raises(AgentResumeCheckpointChanged):
        repository.upsert_goal(prepared, expected_resume=checkpoint)
    assert repository.get_agent_goal(saved_goal.id) == saved_goal
