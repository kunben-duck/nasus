"""Isolated real PG lifecycle transactions; not target, source ACL or Temporal evidence."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.quality_loop.run_plan_case_jobs import RunPlanCaseJobTarget
from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_CANCEL_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.run_plan_case_job_models import RunPlanCaseJobCancellationRecord as Cancellation, RunPlanCaseJobCancellationDeliveryRecord as Delivery
from apps.api.app.infrastructure.persistence.run_plan_case_job_repository import RunPlanCaseJobRepository
from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_run_plan_case_preparation_postgres import original_command


@pytest.fixture
def original_job():
    invocation_id, request, confirmation = original_command()
    actor_id = "case-controller-" + uuid4().hex
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        session.add(UserIdentityRecord(user_id=actor_id, email=actor_id + "@example.invalid",
            display_name="Isolated case controller", role="platform_admin", status="active",
            password_hash="unusable-test-password", created_at=now, updated_at=now))
    result = ConversationRepository(tool_claim_journal=ToolClaimJournal()).claim_tool_invocation_for_execution(
        invocation_id, expected_statuses=("waiting_confirmation",), input_updates=confirmation)
    assert result is not None and result.status == "running"
    return RunPlanCaseJobRepository(), RunPlanCaseJobTarget(project_id=request["project_id"], invocation_id=invocation_id), actor_id


def control(target, actor_id):
    ident = "case-control-" + uuid4().hex
    with session_scope() as session:
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        session.add(ToolInvocationRecord(id=ident, tool_id=CASE_CANCEL_TOOL, status="running", revision=0,
            summary="Isolated independently confirmed cancellation", input_payload={**target.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": actor_id, "confirmed_at": now}))
    return ident


def facts(target):
    with session_scope() as session:
        return (session.get(ToolInvocationRecord, target.invocation_id).status,
            session.get(Cancellation, target.invocation_id) is not None,
            session.get(Delivery, target.invocation_id) is not None,
            session.scalar(select(func.count()).select_from(AuditEventRecord).where(AuditEventRecord.entity_id == target.invocation_id)),
            session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == target.invocation_id)))


def test_prebinding_cancel_late_revocation_rolls_back_status_ledger_audit_and_outbox(original_job):
    repository, target, actor_id = original_job
    ident, calls = control(target, actor_id), []
    def current():
        calls.append(True)
        if len(calls) == 3:
            raise SourceAccessDenied("explicit revocation after original event flush")
    with pytest.raises(SourceAccessDenied):
        repository.cancel(target, control_id=ident, actor_id=actor_id, require_current=current)
    assert len(calls) == 3 and facts(target) == ("running", False, False, 0, 0)


def test_concurrent_independent_cancellations_preserve_one_original_fact_and_event(original_job):
    repository, target, actor_id = original_job
    controls, gate = (control(target, actor_id), control(target, actor_id)), Barrier(2)
    def cancel(ident):
        gate.wait(timeout=10)
        return repository.cancel(target, control_id=ident, actor_id=actor_id, require_current=lambda: None)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(cancel, ident) for ident in controls]
        assert [future.result(timeout=20) for future in futures] == ["cancelled", "cancelled"]
    assert facts(target) == ("cancelled", True, False, 1, 1)
    with session_scope() as session:
        assert session.get(Cancellation, target.invocation_id).control_id in controls
        assert session.get(ToolInvocationRecord, target.invocation_id).revision == 2


def test_delivery_race_and_completed_control_keep_append_only_original_cancellation(original_job):
    repository, target, actor_id = original_job
    ident = control(target, actor_id)
    assert repository.cancel(target, control_id=ident, actor_id=actor_id, require_current=lambda: None) == "cancelled"
    assert target.invocation_id in repository.pending_cancellations()
    with session_scope() as session:
        session.get(ToolInvocationRecord, ident).status = "completed"
    gate = Barrier(2)
    def deliver():
        gate.wait(timeout=10)
        repository.cancellation_delivered(target.invocation_id)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(deliver) for _ in range(2)]
        for future in futures:
            assert future.result(timeout=20) is None
    assert target.invocation_id not in repository.pending_cancellations()
    assert facts(target) == ("cancelled", True, True, 1, 1)
    assert repository.command(target)["scope"] is None
    with session_scope() as session:
        for model in (Cancellation, Delivery):
            for statement in (update(model).where(model.invocation_id == target.invocation_id).values(project_id="changed"),
                    delete(model).where(model.invocation_id == target.invocation_id)):
                with pytest.raises(DBAPIError):
                    with session.begin_nested():
                        session.execute(statement)
        migration = importlib.import_module("apps.api.migrations.versions.0120_run_plan_case_jobs")
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated original"):
                migration.downgrade()


def test_empty_0120_owned_schema_roundtrip_matches_registered_models():
    migration = importlib.import_module("apps.api.migrations.versions.0120_run_plan_case_jobs")
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "case_job_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            assert all(not inspect(connection).has_table(model.__tablename__, schema=namespace) for model in (Cancellation, Delivery))
            migration.upgrade()
        actual = inspect(connection)
        for model in (Cancellation, Delivery):
            table = model.__table__
            columns = actual.get_columns(table.name, schema=namespace)
            assert {item["name"] for item in columns} == set(table.columns.keys())
            assert not any(item["nullable"] for item in columns)
            expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements))
                for fk in table.foreign_key_constraints}
            observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name
                for name in fk["referred_columns"])) for fk in actual.get_foreign_keys(table.name, schema=namespace)}
            assert observed == expected
            assert session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0
