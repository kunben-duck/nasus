"""Isolated PostgreSQL start receipt ownership, replay and transaction checks."""
from uuid import uuid4
import importlib

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations

from apps.api.app.domain.agent.goal_creation import AgentGoalStartIdentity, AgentGoalStartReplayed, ActiveAgentGoalExists
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.infrastructure.persistence.agent_start_models import AgentGoalStartReceiptRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.database import SessionLocal, engine
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_agent_goal_creation_postgres import creation_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_targeted_build_intent_api import fixed_request
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal
from apps.api.app.store import get_runtime_assembly


def receipt(workflow_id):
    with session_scope() as session:
        row = session.get(AgentGoalStartReceiptRecord, workflow_id)
        return None if row is None else {key: getattr(row, key) for key in (
            "schema_version", "workflow_id", "request_digest", "goal_id", "conversation_id", "project_id", "receipt_hash")}


@pytest.mark.parametrize("status", ["pending", "running", "paused", "blocked", "completed", "failed", "cancelled"])
def test_same_start_is_replayed_even_after_the_original_goal_is_terminal(creation_scope, status):
    repository, goal = creation_scope
    identity = AgentGoalStartIdentity.capture(goal.workflow_id, {"fixed": "original", "budget": 0})
    repository.create_goal(goal, start_identity=identity)
    original = receipt(goal.workflow_id)
    assert original == identity.receipt(goal.id, goal.conversation_id, goal.project_id)
    goal.status = status
    repository.upsert_goal(goal)
    retry = goal.model_copy(update={"id": "retry_" + uuid4().hex, "status": "pending"})
    with pytest.raises(AgentGoalStartReplayed) as replay:
        ConversationRepository().create_goal(retry, start_identity=identity)
    assert replay.value.goal_id == goal.id
    assert receipt(goal.workflow_id) == original
    assert repository.list_agent_goals(conversation_id=goal.conversation_id) == [goal]


def test_second_workflow_gets_a_conflict_but_no_receipt_or_ownership(creation_scope):
    repository, goal = creation_scope
    identity = AgentGoalStartIdentity.capture(goal.workflow_id, {})
    repository.create_goal(goal, start_identity=identity)
    second = goal.model_copy(update={"id": "loser_" + uuid4().hex, "workflow_id": "loser_" + uuid4().hex})
    with pytest.raises(ActiveAgentGoalExists) as conflict:
        repository.create_goal(second, start_identity=AgentGoalStartIdentity.capture(second.workflow_id, {}))
    assert conflict.value.goal_id == goal.id
    assert receipt(second.workflow_id) is None
    assert repository.get_agent_goal(goal.id) == goal


def test_changed_start_input_cannot_reuse_a_valid_workflow_receipt(creation_scope):
    repository, goal = creation_scope
    identity = AgentGoalStartIdentity.capture(goal.workflow_id, {"budget": 0})
    repository.create_goal(goal, start_identity=identity)
    with pytest.raises(AgentPlanPolicyViolation) as changed:
        repository.create_goal(goal.model_copy(update={"id": "changed_" + uuid4().hex}),
            start_identity=AgentGoalStartIdentity.capture(goal.workflow_id, {"budget": 1}))
    assert changed.value.code == "agent_start_scope_changed"
    assert receipt(goal.workflow_id) == identity.receipt(goal.id, goal.conversation_id, goal.project_id)


def test_receipt_failure_rolls_back_the_goal_and_releases_the_conversation(creation_scope):
    repository, goal = creation_scope
    identity = AgentGoalStartIdentity.capture(goal.workflow_id, {})

    def reject(session, *args):
        if any(isinstance(row, AgentGoalStartReceiptRecord) for row in session.new):
            raise RuntimeError("injected start receipt failure")

    event.listen(SessionLocal, "before_flush", reject)
    try:
        with pytest.raises(RuntimeError, match="injected start receipt failure"):
            repository.create_goal(goal, start_identity=identity)
    finally:
        event.remove(SessionLocal, "before_flush", reject)
    assert repository.get_agent_goal(goal.id) is None and receipt(goal.workflow_id) is None
    ConversationRepository().create_goal(goal, start_identity=identity)
    assert repository.get_agent_goal(goal.id) == goal


@pytest.mark.parametrize("mutation", ["UPDATE agent_goal_start_receipts SET request_digest = 'changed'",
    "DELETE FROM agent_goal_start_receipts"])
def test_start_receipts_are_append_only_in_postgresql(creation_scope, mutation):
    repository, goal = creation_scope
    identity = AgentGoalStartIdentity.capture(goal.workflow_id, {})
    repository.create_goal(goal, start_identity=identity)
    with pytest.raises(DBAPIError):
        with session_scope() as session:
            session.execute(text(mutation + " WHERE workflow_id = :workflow"), {"workflow": goal.workflow_id})
    assert receipt(goal.workflow_id) == identity.receipt(goal.id, goal.conversation_id, goal.project_id)


def test_foreign_key_prevents_later_projection_from_stealing_start_ownership(creation_scope):
    repository, goal = creation_scope
    identity = AgentGoalStartIdentity.capture(goal.workflow_id, {})
    repository.create_goal(goal, start_identity=identity)
    with pytest.raises(DBAPIError):
        repository.upsert_goal(goal.model_copy(update={"workflow_id": "stolen_workflow"}))
    assert repository.get_agent_goal(goal.id) == goal


def test_composed_application_preserves_start_identity_and_does_not_restart_its_budget_gate(evidence_api):
    import asyncio

    v = evidence_api
    fixed, _ = fixed_request(v)
    loop = get_runtime_assembly().agent_loop_runtime
    planned = AgentGoalProposal(goal_template="system_image_build", title="Durable application entry", summary="Original inputs",
        goal_description="Never release a gate by retrying creation", target_refs=[f"project:{v['project_id']}",
            f"build_plan:{fixed['plan_id']}", f"build_plan_digest:{fixed['plan_digest']}"])
    workflow_id = "composed-start-" + uuid4().hex
    with actor_scope(UserProfile.model_validate(v["owner"])):
        first = asyncio.run(loop.start_goal(v["conversation"].json()["id"], planned, workflow_id=workflow_id))
        repeated = asyncio.run(loop.start_goal(first.conversation_id, planned, workflow_id=workflow_id))
    assert first == repeated and first.workflow_id == workflow_id and first.pause_reason == "waiting_confirmation"
    assert receipt(workflow_id)["goal_id"] == first.id
    original = receipt(workflow_id)
    planned.max_steps += 1
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(AgentPlanPolicyViolation) as changed:
            asyncio.run(loop.start_goal(first.conversation_id, planned, workflow_id=workflow_id))
    assert changed.value.code == "agent_start_scope_changed"
    assert receipt(workflow_id) == original
    assert ConversationRepository().get_agent_goal(first.id) == first


@pytest.mark.parametrize("populated", [False, True], ids=["legacy-upgrade-empty-downgrade", "populated-downgrade-rejected"])
def test_real_migration_preserves_legacy_goals_and_guards_start_receipts(populated):
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    migration = importlib.import_module("apps.api.migrations.versions.0088_agent_goal_start_receipts")
    schema = "start_migration_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        connection.execute(text("CREATE TABLE conversation_sessions (id varchar PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE agent_goals (id varchar PRIMARY KEY, conversation_id varchar NOT NULL, workflow_id varchar)"))
        connection.execute(text("INSERT INTO conversation_sessions VALUES ('conversation')"))
        connection.execute(text("INSERT INTO agent_goals VALUES ('legacy_goal', 'conversation', 'legacy_workflow')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.scalar(text("SELECT count(*) FROM agent_goal_start_receipts")) == 0
            assert connection.scalar(text("SELECT count(*) FROM agent_goals")) == 1
            if populated:
                identity = AgentGoalStartIdentity.capture("legacy_workflow", {})
                # An explicit trusted fixture receipt, not an inferred migration.
                values = identity.receipt("legacy_goal", "conversation", None)
                columns = ", ".join(values)
                parameters = ", ".join(":" + key for key in values)
                connection.execute(text(f"INSERT INTO agent_goal_start_receipts ({columns}) VALUES ({parameters})"), values)
                with pytest.raises(RuntimeError, match="Cannot discard populated"):
                    migration.downgrade()
                assert connection.scalar(text("SELECT count(*) FROM agent_goal_start_receipts")) == 1
            else:
                migration.downgrade()
                assert connection.scalar(text("SELECT to_regclass(:table)"), {"table": schema + ".agent_goal_start_receipts"}) is None
                assert connection.scalar(text("SELECT count(*) FROM agent_goals")) == 1
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
