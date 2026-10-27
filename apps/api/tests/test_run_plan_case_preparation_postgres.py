"""Actual isolated PG claims/rollback/uniqueness; never target or Temporal evidence."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL
from apps.api.app.domain.quality_loop.run_plan_case_preparation import CASE_PREPARATION_MARKER
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_models import RunPlanCasePreparationRecord as Preparation, RunPlanCasePreparationBindingRecord as Binding
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_repository import RunPlanCasePreparationRepository
from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_run_plan_case_execution import inputs


def original_command(selection=None):
    ident = "case-preparation-test-" + uuid4().hex
    _plan, scope, _snapshot, _now = inputs()
    request = deepcopy(selection) if selection else {**deepcopy(scope.selection),
        "project_id": "case-project-" + uuid4().hex, "run_id": "case-run-" + uuid4().hex}
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        session.add(ToolInvocationRecord(id=ident, tool_id=CASE_EXECUTE_TOOL, status="waiting_confirmation",
            summary="Isolated original case claim", input_payload=request, revision=0))
    return ident, request, {"confirmed_by_user": True, "confirmed_actor_id": "isolated-case-owner", "confirmed_at": now}


def test_case_claim_failure_rolls_back_marker_receipt_status_and_confirmation():
    ident, _request, confirmation = original_command()
    class Failing:
        def record(self, session, command):
            ToolClaimJournal().record(session, command)
            session.flush()
            raise RuntimeError("explicit failure after command and receipt flush")
    repository = ConversationRepository(tool_claim_journal=Failing())
    with pytest.raises(RuntimeError, match="explicit failure"):
        repository.claim_tool_invocation_for_execution(ident, expected_statuses=("waiting_confirmation",), input_updates=confirmation)
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        assert row.status == "waiting_confirmation" and row.revision == 0
        assert CASE_PREPARATION_MARKER not in row.input_payload and "confirmed_by_user" not in row.input_payload
        assert session.get(Preparation, ident) is None


def test_original_command_race_has_one_immutable_receipt():
    ident, _request, confirmation = original_command()
    repository = ConversationRepository(tool_claim_journal=ToolClaimJournal())
    gate = Barrier(2)
    def claim():
        gate.wait(timeout=10)
        return repository.claim_tool_invocation_for_execution(ident, expected_statuses=("waiting_confirmation",), input_updates=confirmation)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(claim) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sum(result is not None for result in results) == 1
    assert RunPlanCasePreparationRepository().delivery(ident)["bound"] is False
    with session_scope() as session:
        assert len(session.scalars(select(Preparation).where(Preparation.invocation_id == ident)).all()) == 1
        row = session.get(ToolInvocationRecord, ident)
        assert row.status == "running" and row.revision == 1
        for statement in (update(Preparation).where(Preparation.invocation_id == ident).values(run_id="changed"),
                delete(Preparation).where(Preparation.invocation_id == ident)):
            with pytest.raises(DBAPIError):
                with session.begin_nested(): session.execute(statement)
        migration = importlib.import_module("apps.api.migrations.versions.0119_run_plan_case_preparations")
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated original"):
                migration.downgrade()


def test_two_different_commands_cannot_reserve_the_same_original_project_run():
    first, request, confirm_first = original_command()
    second, _same, confirm_second = original_command(request)
    repository = ConversationRepository(tool_claim_journal=ToolClaimJournal())
    gate = Barrier(2)
    def claim(ident, confirmation):
        gate.wait(timeout=10)
        try:
            result = repository.claim_tool_invocation_for_execution(ident,
                expected_statuses=("waiting_confirmation",), input_updates=confirmation)
            return "claimed", result.id
        except IntegrityError:
            return "duplicate", ident
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(claim, first, confirm_first), workers.submit(claim, second, confirm_second)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(status for status, _ in results) == ["claimed", "duplicate"]
    winner, loser = (next(ident for status, ident in results if status == value) for value in ("claimed", "duplicate"))
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, winner).status == "running"
        row = session.get(ToolInvocationRecord, loser)
        assert row.status == "waiting_confirmation" and row.revision == 0
        assert CASE_PREPARATION_MARKER not in row.input_payload and "confirmed_by_user" not in row.input_payload
        assert session.get(Preparation, loser) is None
        assert len(session.scalars(select(Preparation).where(Preparation.project_id == request["project_id"],
            Preparation.run_id == request["run_id"])).all()) == 1


def test_empty_0119_owned_schema_roundtrip_matches_original_registered_models():
    migration = importlib.import_module("apps.api.migrations.versions.0119_run_plan_case_preparations")
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "case_preparation_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            assert all(not inspect(connection).has_table(model.__tablename__, schema=namespace) for model in (Preparation, Binding))
            migration.upgrade()
        actual = inspect(connection)
        for model in (Preparation, Binding):
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
            triggers = session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = CAST(:table AS regclass)"),
                {"table": namespace + "." + table.name}).scalars().all()
            assert triggers == ["immutable_" + table.name]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
