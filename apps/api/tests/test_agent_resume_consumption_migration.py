import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, InvalidAgentResumeCheckpoint
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.tests.agent_resume_fixtures import paused_goal, resume_transition


@pytest.mark.parametrize("populated", [False, True])
def test_resume_migration_is_additive_preserves_history_and_rejects_mutation(monkeypatch, populated):
    assert engine.url.database.startswith("nasus_test_")
    migration = importlib.import_module("apps.api.migrations.versions.0085_agent_resume_consumptions")
    goal = paused_goal()
    repository = ConversationRepository()
    repository.upsert_goal(goal)
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    repository.upsert_goal(resume_transition(goal), expected_resume=checkpoint)
    schema = "nasus_test_resume_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            model = AgentResumeConsumptionRecord
            columns = {item["name"]: item for item in inspect(connection).get_columns(model.__tablename__, schema=schema)}
            assert columns.keys() == set(model.__table__.columns.keys())
            for column in model.__table__.columns:
                assert columns[column.name]["nullable"] == column.nullable
                assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
            assert connection.scalar(text("SELECT count(*) FROM agent_resume_consumptions")) == 0
            if populated:
                connection.execute(text("INSERT INTO agent_resume_consumptions SELECT * FROM public.agent_resume_consumptions WHERE goal_id = :id"), {"id": goal.id})
                before = dict(connection.execute(text("SELECT * FROM agent_resume_consumptions")).mappings().one())
                for statement in ("UPDATE agent_resume_consumptions SET receipt_hash = 'changed'", "DELETE FROM agent_resume_consumptions"):
                    with pytest.raises(DBAPIError), connection.begin_nested():
                        connection.execute(text(statement))
                with pytest.raises(RuntimeError, match="Cannot discard populated"):
                    migration.downgrade()
                assert dict(connection.execute(text("SELECT * FROM agent_resume_consumptions")).mappings().one()) == before
            else:
                migration.downgrade()
                assert inspect(connection).get_table_names(schema=schema) == []
                migration.upgrade()
                assert connection.scalar(text("SELECT count(*) FROM agent_resume_consumptions")) == 0
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()


def test_consumption_digest_is_scoped_and_detects_damaged_receipt_without_retaining_private_payload():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    value = checkpoint.consumption(resume_transition(goal).model_dump(mode="json"))
    assert set(value) == {"schema", "checkpoint", "transition_digest", "receipt_hash"}
    assert "steps" not in str(value)
    checkpoint.require_consumption(value["transition_digest"], value["receipt_hash"])
    with pytest.raises(InvalidAgentResumeCheckpoint):
        checkpoint.require_consumption("sha256:" + "0" * 64, value["receipt_hash"])
