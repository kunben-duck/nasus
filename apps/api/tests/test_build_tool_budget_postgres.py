"""Cumulative reservations must survive concurrency, rollback and phase changes."""
from concurrent.futures import ThreadPoolExecutor
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import select, text, update, delete
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.agent.agent_models import AgentStep
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.build_tool_budget import BuildToolBudgetExhausted
from apps.api.app.infrastructure.persistence.build_tool_budget_models import BuildToolBudgetRecord, BuildToolConsumptionRecord
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_agent_goal_creation_postgres import creation_scope


def prepare(creation_scope, limit=2):
    repository, goal = creation_scope
    goal.goal_template = "system_image_build"
    goal.status = "running"
    request = {"project_id": goal.project_id, "budget": {"max_tool_calls": limit}}
    goal.steps = [AgentStep(id="original-plan", title="Plan", phase="acting", status="pending",
        selected_tool_id="system_image.build.plan", tool_input_payload=request)]
    repository.create_goal(goal)
    commands = []
    for index in range(3):
        ident = "work_" + uuid4().hex
        payload = {"project_id": goal.project_id, "selected": index}
        step = AgentStep(id=f"step-{index}", title="Read fixed evidence", phase="acting", status="pending",
            selected_tool_id="query.system_image.revisions.read", tool_input_payload=payload)
        goal.steps.append(step)
        command = ToolInvocation(id=ident, tool_id=step.selected_tool_id, conversation_id=goal.conversation_id,
            status="running", summary="Claimed", initiator_actor="agent", initiator_surface="agent_loop",
            input_payload={**payload, "agent_goal_id": goal.id,
                "agent_loop_iteration_id": f"{goal.id}:{step.id}:0"},
            idempotency_key=f"agent-goal:{goal.id}:step:{step.id}:attempt:0")
        repository.upsert_tool_invocation(command)
        commands.append(command)
    repository.upsert_goal(goal)
    return repository, goal, commands


def test_new_goal_budget_is_frozen_but_legacy_history_is_not_backfilled(creation_scope):
    repository, goal, commands = prepare(creation_scope)
    budget, rows = BuildToolBudgetRepository().inspect(goal.id)
    assert budget.max_tool_calls == 2 and budget.origin_kind == "source_intent" and not rows
    with session_scope() as session:
        assert session.get(AgentGoalRecord, goal.id).tool_budget_hash == budget.digest
    goal.status = "paused"
    repository.upsert_goal(goal)
    assert BuildToolBudgetRepository().inspect(goal.id) == (budget, ())
    legacy = goal.model_copy(update={"id": "legacy_" + uuid4().hex})
    repository.upsert_goal(legacy)
    assert BuildToolBudgetRepository().inspect(legacy.id) is None


def test_phase_extension_and_process_reconstruction_cannot_reset_consumption(creation_scope):
    repository, goal, commands = prepare(creation_scope)
    ledger = BuildToolBudgetRepository()
    assert ledger.reserve(commands[0])
    budget, first = ledger.inspect(goal.id)
    # Additional independently prepared work cannot replace the original envelope.
    goal.target_refs = ["source_manifest:new-phase-inputs"]
    goal.steps[0].tool_input_payload["budget"]["max_tool_calls"] = 1000
    repository.upsert_goal(goal)
    assert BuildToolBudgetRepository().reserve(commands[1])
    assert BuildToolBudgetRepository().reserve(commands[0])
    with pytest.raises(BuildToolBudgetExhausted):
        BuildToolBudgetRepository().reserve(commands[2])
    original, rows = ledger.inspect(goal.id)
    assert original == budget and len(rows) == 2 and rows[0] == first[0]
    assert rows[1]["previous_hash"] != rows[0]["previous_hash"]
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.agent_goal_id == goal.id)).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == goal.id)).all()
        assert len(audits) == len(events) == 2
        assert all("selected" not in str(item.event_payload) for item in events)


def test_competing_reservations_cannot_exceed_the_original_ceiling(creation_scope):
    _, goal, commands = prepare(creation_scope, limit=1)

    def reserve(command):
        try:
            return BuildToolBudgetRepository().reserve(command)
        except BuildToolBudgetExhausted:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, commands[:2]))
    assert sorted(results) == [False, True]
    assert len(BuildToolBudgetRepository().inspect(goal.id)[1]) == 1


def test_failed_outbox_commit_does_not_consume_a_slot_or_audit(creation_scope, monkeypatch):
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    _, goal, commands = prepare(creation_scope)
    original = EventOutboxRepository.append

    def reject(*args, **kwargs):
        raise RuntimeError("injected outbox failure")

    monkeypatch.setattr(EventOutboxRepository, "append", reject)
    with pytest.raises(RuntimeError, match="injected"):
        BuildToolBudgetRepository().reserve(commands[0])
    assert not BuildToolBudgetRepository().inspect(goal.id)[1]
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.agent_goal_id == goal.id)).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    assert BuildToolBudgetRepository().reserve(commands[0])


@pytest.mark.parametrize("change", ["input", "iteration", "project", "conversation"])
def test_forged_command_cannot_drain_a_goal_budget(creation_scope, change):
    repository, goal, commands = prepare(creation_scope)
    forged = commands[0].model_copy(deep=True)
    if change == "conversation":
        forged.conversation_id = "other"
    elif change == "project":
        forged.input_payload["project_id"] = "other"
    elif change == "iteration":
        forged.input_payload["agent_loop_iteration_id"] = "other"
    else:
        forged.input_payload["selected"] = 99
    repository.upsert_tool_invocation(forged)
    with pytest.raises(BuildPlanIntegrityError):
        BuildToolBudgetRepository().reserve(forged)
    assert not BuildToolBudgetRepository().inspect(goal.id)[1]


def test_budget_pin_and_consumption_are_append_only(creation_scope):
    _, goal, commands = prepare(creation_scope)
    BuildToolBudgetRepository().reserve(commands[0])
    statements = [update(AgentGoalRecord).where(AgentGoalRecord.id == goal.id).values(tool_budget_hash=None),
        update(BuildToolBudgetRecord).where(BuildToolBudgetRecord.goal_id == goal.id).values(content_hash="changed"),
        delete(BuildToolConsumptionRecord).where(BuildToolConsumptionRecord.goal_id == goal.id)]
    for statement in statements:
        with pytest.raises(DBAPIError):
            with session_scope() as session:
                session.execute(statement)
    assert len(BuildToolBudgetRepository().inspect(goal.id)[1]) == 1


def test_missing_ledger_for_a_marked_goal_fails_closed_without_recreation(creation_scope):
    _, goal, commands = prepare(creation_scope)
    # Simulate restore corruption with administrator-only trigger bypass.
    with session_scope() as session:
        session.execute(text("ALTER TABLE image_build_tool_budgets DISABLE TRIGGER immutable_image_build_tool_budgets"))
        session.execute(delete(BuildToolBudgetRecord).where(BuildToolBudgetRecord.goal_id == goal.id))
        session.execute(text("ALTER TABLE image_build_tool_budgets ENABLE TRIGGER immutable_image_build_tool_budgets"))
    with pytest.raises(BuildPlanIntegrityError, match="missing"):
        BuildToolBudgetRepository().reserve(commands[0])
    with session_scope() as session:
        assert session.get(BuildToolBudgetRecord, goal.id) is None


def test_changed_canonical_input_cannot_be_silently_recharged(creation_scope):
    repository, goal, commands = prepare(creation_scope)
    BuildToolBudgetRepository().reserve(commands[0])
    changed = commands[0].model_copy(deep=True)
    changed.input_payload["selected"] = "changed after reservation"
    repository.upsert_tool_invocation(changed)
    with pytest.raises(BuildPlanIntegrityError, match="integrity"):
        BuildToolBudgetRepository().reserve(changed)
    with session_scope() as session:
        assert len(session.scalars(select(BuildToolConsumptionRecord).where(BuildToolConsumptionRecord.goal_id == goal.id)).all()) == 1


def test_a_different_command_cannot_reuse_the_same_work_identity(creation_scope):
    repository, goal, commands = prepare(creation_scope)
    ledger = BuildToolBudgetRepository()
    ledger.reserve(commands[0])
    duplicate = commands[0].model_copy(update={"id": "duplicate_" + uuid4().hex})
    repository.upsert_tool_invocation(duplicate)
    with pytest.raises(BuildPlanIntegrityError, match="another canonical"):
        ledger.reserve(duplicate)
    assert len(ledger.inspect(goal.id)[1]) == 1


def test_explicit_new_attempt_consumes_another_slot_not_a_new_budget(creation_scope):
    repository, goal, commands = prepare(creation_scope)
    ledger = BuildToolBudgetRepository()
    ledger.reserve(commands[0])
    budget, first = ledger.inspect(goal.id)
    step = goal.steps[1]
    step.tool_input_payload["agent_loop_attempt"] = 1
    repository.upsert_goal(goal)
    retry = commands[0].model_copy(deep=True)
    retry.id = "retry_" + uuid4().hex
    retry.input_payload.update(agent_loop_attempt=1, agent_loop_iteration_id=f"{goal.id}:{step.id}:1")
    retry.idempotency_key = f"agent-goal:{goal.id}:step:{step.id}:attempt:1"
    repository.upsert_tool_invocation(retry)
    assert ledger.reserve(retry)
    current, rows = ledger.inspect(goal.id)
    assert current == budget and len(rows) == 2 and rows[0] == first[0]
    assert rows[0]["work_key"] != rows[1]["work_key"]
    with pytest.raises(BuildToolBudgetExhausted):
        ledger.reserve(commands[1])


@pytest.mark.parametrize("populated", [False, True])
def test_migration_does_not_invent_old_consumption_and_preserves_populated_history(populated):
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    migration = importlib.import_module("apps.api.migrations.versions.0092_build_tool_budget")
    schema = "tool_budget_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            connection.execute(text("CREATE TABLE agent_goals (id varchar PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE tool_invocations (id varchar PRIMARY KEY)"))
            connection.execute(text("INSERT INTO agent_goals VALUES ('legacy')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.scalar(text("SELECT tool_budget_hash FROM agent_goals")) is None
                assert connection.scalar(text("SELECT count(*) FROM image_build_tool_budgets")) == 0
                if populated:
                    connection.execute(text("UPDATE agent_goals SET tool_budget_hash = 'original'"))
                    with pytest.raises(RuntimeError, match="Cannot discard"):
                        migration.downgrade()
                else:
                    migration.downgrade()
                    migration.upgrade()
                    assert connection.scalar(text("SELECT tool_budget_hash FROM agent_goals")) is None
        finally:
            transaction.rollback()
