"""Offline adapter/DDL contract checks; no claim of actual PG transaction testing."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import io
from types import SimpleNamespace

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest

from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import (
    CASE_CLAIM_SCHEMA, RunPlanCaseLease, RunPlanCaseExecutionInvalid, RunPlanCaseWorkLost, execution_roster,
)
from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import (
    RunPlanCaseWorkRecord as Work, RunPlanCaseClaimRecord as Claim, RunPlanCaseLeaseRecord as Lease,
    RunPlanCaseOutcomeRecord as Outcome, RunPlanCaseCancellationRecord as Cancellation,
)
from apps.api.app.infrastructure.persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository as Repository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, UserIdentityRecord
from apps.api.tests.test_run_plan_case_execution import inputs


def work_row():
    plan, scope, snapshot, now = inputs()
    roster = execution_roster(plan, scope)
    value = Repository._work_value(scope, roster, now.isoformat())
    row = Work(**{key: value[key] for key in Work.__table__.columns.keys() if key != "content_hash"},
        content_hash=acceptance_digest(value))
    return scope, roster, row, snapshot, now


@pytest.mark.parametrize("fault", ["scope", "roster", "column", "hash", "missing"])
def test_work_read_rejects_incomplete_or_rebound_original_inputs(fault):
    scope, roster, row, _snapshot, _now = work_row()
    if fault == "scope": row.scope = {**row.scope, "actor_id": "other"}
    elif fault == "roster": row.roster = row.roster[:-1]
    elif fault == "column": row.run_plan_id = "other"
    elif fault == "hash": row.content_hash = acceptance_digest("wrong")
    else: row = None
    session = SimpleNamespace(get=lambda _model, _id: row)
    with pytest.raises(RunPlanCaseExecutionInvalid): Repository._work(session, scope, roster)


def test_original_work_read_preserves_all_immutable_payloads():
    scope, roster, row, _snapshot, _now = work_row()
    before = deepcopy(row.scope)
    assert Repository._work(SimpleNamespace(get=lambda _model, _id: row), scope, roster) is row
    assert row.scope == before


@pytest.mark.parametrize("fault", ["payload", "column", "hash", "schema"])
def test_fact_columns_and_native_digest_are_verified_not_just_status(fault):
    scope, roster, _row, _snapshot, now = work_row()
    value = dict(schema=CASE_CLAIM_SCHEMA, claim_id="original", project_id=scope.project_id,
        work_id=scope.work_id, case_id=roster[0]["case_id"], ordinal=0, owner_id="owner", epoch=1,
        recorded_at=now.isoformat(), scope_digest=scope.digest,
        case_digest=roster[0]["case_digest"], command_digest=roster[0]["command_digest"])
    row = Repository._row(Claim, value)
    if fault == "payload": row.payload = {**row.payload, "epoch": 2}
    elif fault == "column": row.owner_id = "other"
    elif fault == "hash": row.content_hash = acceptance_digest("wrong")
    else: row.payload = {**row.payload, "schema": "other"}
    with pytest.raises(RunPlanCaseExecutionInvalid): Repository._payload(row, CASE_CLAIM_SCHEMA)


def test_canonical_query_extracts_full_original_command_and_no_fixture_downgrade():
    scope, _roster, _row, snapshot, now = work_row()
    command = SimpleNamespace(**snapshot)

    def scalar(query):
        return command if query.column_descriptions[0].get("entity") is ToolInvocationRecord else now

    session = SimpleNamespace(scalar=scalar, get=lambda *_: None)
    assert Repository._command(session, scope) is command
    command.tool_id = "quality.http_fixture.execute"
    with pytest.raises(RunPlanCaseExecutionInvalid): Repository._command(session, scope)


@pytest.mark.parametrize("fault", ["expired", "owner", "epoch", "cancelled", "future_clock"])
def test_production_live_fence_rejects_stale_or_cancelled_worker(monkeypatch, fault):
    scope, _roster, _work, _snapshot, now = work_row()
    lease = RunPlanCaseLease(scope, "owner", 1)
    from datetime import timedelta
    row = Lease(work_id=scope.work_id, project_id=scope.project_id, owner_id="owner", epoch=1,
        acquired_at=now, renewed_at=now, expires_at=now + timedelta(seconds=90))
    if fault == "expired": row.expires_at = now
    elif fault == "owner": row.owner_id = "new"
    elif fault == "epoch": row.epoch = 2
    elif fault == "future_clock": row.acquired_at = now + timedelta(seconds=200)
    monkeypatch.setattr(Repository, "_command", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(Repository, "_actor", staticmethod(lambda *args: None))
    monkeypatch.setattr(Repository, "_cancelled", staticmethod(lambda *args: fault == "cancelled"))

    def scalar(query):
        return row if query.column_descriptions[0].get("entity") is Lease else now

    with pytest.raises(RunPlanCaseWorkLost):
        Repository._live(SimpleNamespace(scalar=scalar), lease, require_current=lambda: None)


@pytest.mark.parametrize("role,status,expected", [("qa_lead", "active", True), ("project_admin", "active", True),
    ("viewer", "active", False), ("qa_lead", "disabled", False), ("qa_lead", "active_duplicate", False)])
def test_production_actor_fence_requires_current_nonambiguous_execution_role(role, status, expected):
    scope, _roster, _row, _snapshot, _now = work_row()
    actor = SimpleNamespace(status="disabled" if status == "disabled" else "active", role="member")
    roles = [SimpleNamespace(role=role)] * (2 if status == "active_duplicate" else 1)
    session = SimpleNamespace(scalar=lambda _query: actor,
        scalars=lambda _query: SimpleNamespace(all=lambda: roles))
    if expected: Repository._actor(session, scope.project_id, scope.actor_id)
    else:
        with pytest.raises(PermissionError): Repository._actor(session, scope.project_id, scope.actor_id)


def test_fixed_0118_migration_emits_complete_postgresql_ddl_without_connection():
    module = importlib.import_module("apps.api.migrations.versions.0118_run_plan_case_work")
    stream = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": stream})
    with Operations.context(context): module.upgrade()
    sql = stream.getvalue()
    assert module.down_revision == "0117_fixture_preparation_cancel"
    for table in module.TABLES: assert f"CREATE TABLE {table}" in sql
    assert sql.count("EXECUTE FUNCTION nasus_reject_image_revision_mutation()") == 4
    assert "nasus_guard_run_plan_case_lease()" in sql and "Cannot steal a live original case lease" in sql
    assert "REFERENCES quality_run_plans" in sql and "INTERVAL '90 seconds'" in sql
    assert "INSERT INTO" not in sql and "quality_runs" not in sql
    assert "CREATE TABLE" in sql and "BEFORE UPDATE OR DELETE" in sql


def test_fixed_0118_table_contract_matches_registered_models_without_future_orm_generation(monkeypatch):
    from sqlalchemy import Table, MetaData
    module = importlib.import_module("apps.api.migrations.versions.0118_run_plan_case_work")
    tables = {}

    class Capture:
        def create_table(self, name, *parts):
            tables[name] = Table(name, MetaData(), *parts)

        def execute(self, _sql):
            pass

    monkeypatch.setattr(module, "op", Capture())
    module.upgrade()
    models = (Work, Lease, Claim, Outcome, Cancellation)
    assert set(tables) == {model.__tablename__ for model in models}
    for model in models:
        original, generated = tables[model.__tablename__], model.__table__
        shape = lambda table: {(item.name, str(item.type), item.nullable, item.primary_key) for item in table.columns}
        assert shape(original) == shape(generated)
        fks = lambda table: {(tuple(item.column_keys), tuple(element.target_fullname for element in item.elements))
            for item in table.foreign_key_constraints}
        assert fks(original) == fks(generated)


def test_fresh_case_worker_and_repository_imports_never_connect_or_use_sqlite(tmp_path):
    import os
    import subprocess
    import sys
    script = """
from sqlalchemy.engine import Engine
def refuse(*args, **kwargs):
    raise AssertionError('case module import must not connect to any database')
Engine.connect = refuse
from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.application.quality_loop.run_plan_case_inputs import RunPlanCaseInputApplicationService
from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from apps.api.app.infrastructure.persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_repository import RunPlanCasePreparationRepository
from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
from apps.api.app.infrastructure.runner.run_plan_case_runtime import compose_run_plan_cases
from apps.api.app.infrastructure.storage.run_plan_case_artifacts import RunPlanCaseArtifacts
from apps.api.app.bootstrap.container import ApplicationContainer
from apps.api.app.infrastructure.persistence.database import get_database_url
assert get_database_url().startswith('postgresql+psycopg://')
assert 'run_plan_cases' in ApplicationContainer.__dataclass_fields__
print('case modules imported without database connections')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=20,
        env={**os.environ, "NASUS_DATABASE_URL": "postgresql+psycopg://contract@127.0.0.1:1/nasus_case_contract",
            "NASUS_AUTO_CREATE_TABLES": "false"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "case modules imported without database connections"
