"""Owned empty-schema PG migration rehearsal; not a target execution test."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import (
    RunPlanCaseWorkRecord, RunPlanCaseLeaseRecord, RunPlanCaseClaimRecord,
    RunPlanCaseOutcomeRecord, RunPlanCaseCancellationRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_case_work_empty_pg_schema_roundtrip_matches_original_models():
    module = importlib.import_module("apps.api.migrations.versions.0118_run_plan_case_work")
    models = (RunPlanCaseWorkRecord, RunPlanCaseLeaseRecord, RunPlanCaseClaimRecord,
        RunPlanCaseOutcomeRecord, RunPlanCaseCancellationRecord)
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "case_work_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.downgrade()
            assert all(not inspect(connection).has_table(model.__tablename__, schema=namespace) for model in models)
            module.upgrade()
        actual = inspect(connection)
        for model in models:
            table = model.__table__
            columns = actual.get_columns(table.name, schema=namespace)
            assert {item["name"] for item in columns} == set(table.columns.keys())
            assert {item["name"] for item in columns if item["nullable"]} == set()
            expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements))
                for fk in table.foreign_key_constraints}
            observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name
                for name in fk["referred_columns"])) for fk in actual.get_foreign_keys(table.name, schema=namespace)}
            assert observed == expected
            assert session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0
            triggers = session.execute(text("""SELECT tgname FROM pg_trigger
                WHERE NOT tgisinternal AND tgrelid = CAST(:table AS regclass)"""),
                {"table": namespace + "." + table.name}).scalars().all()
            prefix = "guarded_" if model is RunPlanCaseLeaseRecord else "immutable_"
            assert triggers == [prefix + table.name]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
