"""Actual PG original cancellation transactions; no Runner or Temporal transport."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobTarget
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FALSE_AUTHORITIES
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import (
    AuditEventRecord, ProjectRecord, ProjectRoleBindingRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord,
)
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord as Intent
from apps.api.app.infrastructure.persistence.http_fixture_job_models import HttpFixtureCancellationRecord as BoundCancellation
from apps.api.app.infrastructure.persistence.http_fixture_job_repository import HttpFixtureJobRepository
from apps.api.app.infrastructure.persistence.http_fixture_preparation_cancel_models import (
    HttpFixturePreparationCancellationRecord as Cancellation, HttpFixturePreparationCancellationDeliveryRecord as Delivery,
)
from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import (
    HttpFixturePreparationRecord as Preparation, HttpFixturePreparationBindingRecord as Binding,
)
from apps.api.app.infrastructure.persistence.http_fixture_preparation_repository import HttpFixturePreparationJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


@pytest.fixture
def original_preparation():
    project_id, actor_id, control_id, invocation_id = (uuid4().hex for _ in range(4))
    target = HttpFixtureJobTarget(project_id=project_id, invocation_id=invocation_id)
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        confirmed = session.scalar(select(func.clock_timestamp())).isoformat()
        session.add(ProjectRecord(id=project_id, name="Isolated preparation cancellation", code="TEST", summary="No target execution"))
        session.add(UserIdentityRecord(user_id=actor_id, email=actor_id + "@example.test", display_name="Isolated administrator",
            role="qa_lead", password_hash="not-a-login-credential", created_at=confirmed, updated_at=confirmed))
        session.add(ProjectRoleBindingRecord(binding_id=uuid4().hex, project_id=project_id, user_id=actor_id,
            role="project_admin", scope_key="project:" + project_id, scope_ref=project_id,
            created_at=confirmed, updated_at=confirmed, created_by=actor_id))
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=FIXTURE_COMMAND_TOOL, status="waiting_confirmation",
            summary="Original preparation; no execution grant is issued", revision=0,
            input_payload={"project_id": project_id, "grant_id": "not-issued-" + uuid4().hex,
                "grant_digest": acceptance_digest("not-an-execution-grant"), "operation": "setup"}))
        session.add(ToolInvocationRecord(id=control_id, tool_id=FIXTURE_CANCEL_TOOL, status="running",
            summary="Independent original cancellation control", input_payload={**target.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": actor_id, "confirmed_at": confirmed}, revision=1))
    repository = ConversationRepository(tool_claim_journal=HttpFixturePreparationJournal())
    assert repository.claim_tool_invocation_for_execution(invocation_id, expected_statuses=("waiting_confirmation",),
        input_updates={"confirmed_by_user": True, "confirmed_actor_id": actor_id, "confirmed_at": confirmed}) is not None
    jobs = HttpFixtureJobRepository()
    with session_scope() as session:
        original = deepcopy(session.get(ToolInvocationRecord, invocation_id).input_payload)
        preparation = deepcopy(session.get(Preparation, invocation_id).payload)
    return SimpleNamespace(target=target, actor_id=actor_id, control_id=control_id, jobs=jobs, original=original,
        preparation=preparation, authority=jobs.delivery(invocation_id)["authority"])


def cancel(v):
    return v.jobs.cancel(v.target, control_id=v.control_id, actor_id=v.actor_id, require_current=lambda: None)


def records(session, model, ident):
    return session.scalars(select(model).where(model.entity_id == ident)).all()


def test_original_preparation_cancel_rolls_back_terminal_fact_audit_and_partial_outbox(original_preparation, monkeypatch):
    v = original_preparation
    append, calls = EventOutboxRepository.append, []
    def interrupted(self, event, **kwargs):
        result = append(self, event, **kwargs)
        calls.append(event.event_type)
        if len(calls) == 2: raise RuntimeError("explicit failure after cancellation outbox writes")
        return result
    with monkeypatch.context() as outage:
        outage.setattr(EventOutboxRepository, "append", interrupted)
        with pytest.raises(RuntimeError, match="outbox writes"): cancel(v)
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, v.target.invocation_id)
        assert row.status == "running" and row.revision == 1 and row.input_payload == v.original
        assert session.get(Cancellation, row.id) is None and session.get(Delivery, row.id) is None
        assert session.get(Intent, row.id) is None and session.get(Binding, row.id) is None
        assert session.get(Preparation, row.id).payload == v.preparation
        assert records(session, AuditEventRecord, row.id) == records(session, SSEEventOutboxRecord, row.id) == []
    assert cancel(v) == "cancelled"
    assert cancel(v) == "cancelled"
    assert (v.target.invocation_id, v.target.project_id) in v.jobs.pending_cancellations()
    v.jobs.cancellation_delivered(v.target)
    v.jobs.cancellation_delivered(v.target)
    assert (v.target.invocation_id, v.target.project_id) not in v.jobs.pending_cancellations()
    assert v.jobs.finish(v.authority, "failed") == "cancelled"
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, v.target.invocation_id)
        fact = session.get(Cancellation, row.id)
        assert row.status == "cancelled" and row.revision == 2 and row.input_payload == v.original
        assert fact.preparation_digest == acceptance_digest(v.preparation) and fact.actor_id == v.actor_id
        assert session.get(Delivery, row.id).cancellation_digest == fact.content_hash
        assert all(fact.payload[key] is False for key in FALSE_AUTHORITIES)
        assert session.get(Intent, row.id) is None and session.get(Binding, row.id) is None
        assert session.get(BoundCancellation, row.id) is None
        assert len(records(session, AuditEventRecord, row.id)) == len(records(session, SSEEventOutboxRecord, row.id)) == 3
        for model in (Cancellation, Delivery):
            for statement in (update(model).where(model.invocation_id == row.id).values(content_hash="changed"),
                    delete(model).where(model.invocation_id == row.id)):
                with pytest.raises(DBAPIError):
                    with session.begin_nested(): session.execute(statement)
        migration = importlib.import_module("apps.api.migrations.versions.0117_fixture_preparation_cancel")
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated"): migration.downgrade()
        assert session.get(Preparation, row.id).payload == v.preparation


def test_pg_preparation_cancel_and_failure_compete_for_one_original_terminal_state(original_preparation):
    v = original_preparation
    gate = Barrier(2)
    def terminate(operation):
        gate.wait(timeout=10)
        return cancel(v) if operation == "cancel" else v.jobs.finish(v.authority, "failed")
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(terminate, operation) for operation in ("cancel", "fail")]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1] and results[0] in {"cancelled", "failed"}
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, v.target.invocation_id)
        fact = session.get(Cancellation, row.id)
        assert row.status == results[0] and row.revision == 2 and row.input_payload == v.original
        assert (fact is not None) == (row.status == "cancelled")
        expected = 2 if fact is not None else 1
        assert len(records(session, AuditEventRecord, row.id)) == len(records(session, SSEEventOutboxRecord, row.id)) == expected
        assert session.get(Intent, row.id) is None and session.get(Binding, row.id) is None
        assert session.get(Preparation, row.id).payload == v.preparation
