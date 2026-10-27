"""0115 isolated-schema PG roundtrip; offline collection is not execution proof."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.http_fixture_job_models import HttpFixtureCancellationRecord, HttpFixtureCancellationDeliveryRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_fixture_cancellation_migration_has_exact_immutable_parents_and_no_backfill():
    migration = importlib.import_module("apps.api.migrations.versions.0115_fixture_job_cancellations")
    tables = (HttpFixtureCancellationRecord.__table__, HttpFixtureCancellationDeliveryRecord.__table__)
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_cancellations_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert all(session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0 for table in tables)
            migration.downgrade()
            assert all(not inspect(connection).has_table(table.name, schema=namespace) for table in tables)
            migration.upgrade()
        for table in tables:
            actual = inspect(connection)
            columns = actual.get_columns(table.name, schema=namespace)
            assert {column["name"] for column in columns} == set(table.columns.keys())
            assert not any(column["nullable"] for column in columns)
            expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements))
                for fk in table.foreign_key_constraints}
            observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name for name in fk["referred_columns"]))
                for fk in actual.get_foreign_keys(table.name, schema=namespace)}
            assert observed == expected
            assert session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid=CAST(:table AS regclass)"),
                {"table": namespace + "." + table.name}).scalars().all() == ["immutable_" + table.name]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
