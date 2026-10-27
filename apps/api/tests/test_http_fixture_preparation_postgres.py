"""Real PG claim races/rollback; no target, native grant or Temporal claim."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL
from apps.api.app.domain.quality_loop.http_fixture_preparation import PREPARATION_MARKER
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.http_fixture_job_repository import HttpFixtureJobRepository
from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import HttpFixturePreparationRecord as Preparation
from apps.api.app.infrastructure.persistence.http_fixture_preparation_repository import HttpFixturePreparationJournal as Journal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def original_command():
    ident = "preparation-test-" + uuid4().hex
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        confirmed = session.scalar(select(func.clock_timestamp())).isoformat()
        # Intentionally invalid selection: the claim is not a native grant or
        # execution approval, and only its locked rejection is tested here.
        session.add(ToolInvocationRecord(id=ident, tool_id=FIXTURE_COMMAND_TOOL, status="waiting_confirmation",
            summary="Isolated original preparation command", input_payload={"project_id": "test-" + uuid4().hex,
                "operation": "invalid"}, revision=0))
    return ident, {"confirmed_by_user": True, "confirmed_actor_id": "isolated-admin", "confirmed_at": confirmed}


def test_preparation_claim_failure_rolls_back_receipt_status_confirmation_and_marker():
    ident, confirmation = original_command()
    class FailingJournal:
        def record(self, session, row):
            Journal().record(session, row)
            session.flush()
            raise RuntimeError("explicit failure after both original claim and receipt were flushed")
    repository = ConversationRepository(tool_claim_journal=FailingJournal())
    with pytest.raises(RuntimeError, match="explicit failure"):
        repository.claim_tool_invocation_for_execution(ident, expected_statuses=("waiting_confirmation",), input_updates=confirmation)
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        assert row.status == "waiting_confirmation" and row.revision == 0
        assert PREPARATION_MARKER not in row.input_payload and "confirmed_by_user" not in row.input_payload
        assert session.get(Preparation, ident) is None


def test_pg_claim_race_has_one_receipt_and_rejection_outbox_failure_rolls_back(monkeypatch):
    ident, confirmation = original_command()
    repository = ConversationRepository(tool_claim_journal=Journal())
    gate = Barrier(2)
    def claim():
        gate.wait(timeout=10)
        return repository.claim_tool_invocation_for_execution(ident, expected_statuses=("waiting_confirmation",), input_updates=confirmation)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(claim) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sum(result is not None for result in results) == 1
    jobs = HttpFixtureJobRepository()
    status, authority = jobs.failure_command(ident)
    assert status == "running" and jobs.delivery(ident)["bound"] is False
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        original_payload = dict(row.input_payload)
        assert row.revision == 1 and row.status == "running"
        assert len(session.scalars(select(Preparation).where(Preparation.invocation_id == ident)).all()) == 1
        assert session.get(Preparation, ident).request_digest == authority.request_digest
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    def unavailable(*args, **kwargs): raise RuntimeError("explicit transactional outbox failure")
    with monkeypatch.context() as outage:
        outage.setattr(EventOutboxRepository, "append", unavailable)
        with pytest.raises(RuntimeError, match="outbox failure"): jobs.finish(authority, "failed")
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        assert row.status == "running" and row.revision == 1 and row.input_payload == original_payload
        assert session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident)).all() == []
        assert session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all() == []
    assert jobs.finish(authority, "failed") == "failed"
    assert jobs.finish(authority, "failed") == "failed"
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        assert row.revision == 2 and row.input_payload == original_payload
        assert len(session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident)).all()) == 1
        assert len(session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()) == 1
        for statement in (update(Preparation).where(Preparation.invocation_id == ident).values(content_hash="changed"),
                delete(Preparation).where(Preparation.invocation_id == ident)):
            with pytest.raises(DBAPIError):
                with session.begin_nested(): session.execute(statement)
        migration = importlib.import_module("apps.api.migrations.versions.0116_fixture_preparation_receipts")
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated"):
                migration.downgrade()
        assert session.get(Preparation, ident).request_digest == authority.request_digest
