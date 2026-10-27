"""Clock migrations and resume accounting use disposable real PostgreSQL."""
from datetime import timedelta
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.tests.test_agent_active_runtime import START
from apps.api.tests.test_agent_goal_creation_postgres import creation_scope


@pytest.mark.parametrize("populated", [False, True])
def test_clock_migration_never_backfills_history_and_cannot_discard_new_accounting(populated):
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    migration = importlib.import_module("apps.api.migrations.versions.0089_agent_active_runtime")
    schema = "clock_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            connection.execute(text("CREATE TABLE agent_goals (id varchar PRIMARY KEY, started_at varchar)"))
            connection.execute(text("INSERT INTO agent_goals VALUES ('legacy', '2026-10-01T00:00:00+00:00')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                before = dict(connection.execute(text("SELECT * FROM agent_goals")).mappings().one())
                assert before == {"id": "legacy", "started_at": "2026-10-01T00:00:00+00:00",
                    "active_runtime_ms": None, "active_started_at": None}
                column = next(item for item in inspect(connection).get_columns("agent_goals", schema=schema) if item["name"] == "active_runtime_ms")
                assert column["nullable"] and column["default"] is None and str(column["type"]) == "BIGINT"
                for statement in ("UPDATE agent_goals SET active_runtime_ms = -1",
                        "UPDATE agent_goals SET active_started_at = '2026-10-08T00:00:00+00:00'"):
                    with pytest.raises(DBAPIError), connection.begin_nested():
                        connection.execute(text(statement))
                if populated:
                    connection.execute(text("UPDATE agent_goals SET active_runtime_ms = 0"))
                    with pytest.raises(RuntimeError, match="Cannot discard populated"):
                        migration.downgrade()
                    assert connection.scalar(text("SELECT active_runtime_ms FROM agent_goals")) == 0
                else:
                    migration.downgrade()
                    assert dict(connection.execute(text("SELECT * FROM agent_goals")).mappings().one()) == {key: before[key] for key in ("id", "started_at")}
                    migration.upgrade()
                    assert dict(connection.execute(text("SELECT * FROM agent_goals")).mappings().one()) == before
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()


def test_clock_survives_repository_reconstruction_and_resume_consumption(creation_scope):
    repository, goal = creation_scope
    goal.active_runtime_ms = 125
    goal.status = "paused"
    goal.pause_reason = "missing_captured_code"
    goal.started_at = (START - timedelta(days=2)).isoformat()
    repository.create_goal(goal)
    original = goal.model_dump(mode="json")
    checkpoint = AgentResumeCheckpoint.capture(original)
    prepared = ConversationRepository().get_agent_goal(goal.id)
    AgentGoalStateMachine(clock=lambda: START).start_goal(prepared)
    ConversationRepository().upsert_goal(prepared, expected_resume=checkpoint)
    assert ConversationRepository().get_agent_goal(goal.id) == prepared
    assert ConversationRepository().is_resume_consumed(checkpoint)
    AgentGoalStateMachine(clock=lambda: START + timedelta(milliseconds=375)).complete_goal(prepared)
    ConversationRepository().upsert_goal(prepared)
    reloaded = ConversationRepository().get_agent_goal(goal.id)
    assert reloaded.active_runtime_ms == 500 and reloaded.active_started_at is None
    assert reloaded.started_at == original["started_at"]
    with pytest.raises(AgentResumeCheckpointChanged):
        ConversationRepository().upsert_goal(prepared.model_copy(update={"status": "running", "active_started_at": START.isoformat()}), expected_resume=checkpoint)
    assert ConversationRepository().get_agent_goal(goal.id) == reloaded


def test_concurrent_counter_change_invalidates_the_whole_resume_precondition(creation_scope):
    repository, goal = creation_scope
    goal.status = "paused"
    goal.active_runtime_ms = 500
    repository.create_goal(goal)
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    prepared = goal.model_copy(deep=True)
    AgentGoalStateMachine(clock=lambda: START).start_goal(prepared)
    goal.active_runtime_ms += 1
    repository.upsert_goal(goal)
    with pytest.raises(AgentResumeCheckpointChanged):
        ConversationRepository().upsert_goal(prepared, expected_resume=checkpoint)
    assert ConversationRepository().get_agent_goal(goal.id) == goal
    assert not ConversationRepository().is_resume_consumed(checkpoint)


def test_legacy_repository_round_trip_keeps_the_v1_checkpoint(creation_scope):
    repository, goal = creation_scope
    goal.status = "paused"
    original = goal.model_dump(mode="json")
    checkpoint = AgentResumeCheckpoint.capture(original)
    repository.create_goal(goal)
    reloaded = ConversationRepository().get_agent_goal(goal.id)
    assert reloaded.model_dump(mode="json") == original
    checkpoint.require_matches(reloaded.model_dump(mode="json"))
