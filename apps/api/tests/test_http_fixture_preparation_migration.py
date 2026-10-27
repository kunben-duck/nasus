"""0116/0117 isolated PostgreSQL schemas; collection is not execution."""
import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import HttpFixturePreparationRecord, HttpFixturePreparationBindingRecord
from apps.api.app.infrastructure.persistence.http_fixture_preparation_cancel_models import HttpFixturePreparationCancellationRecord, HttpFixturePreparationCancellationDeliveryRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


@pytest.mark.parametrize("module,models", [
    ("0116_fixture_preparation_receipts", (HttpFixturePreparationRecord, HttpFixturePreparationBindingRecord)),
    ("0117_fixture_preparation_cancel", (HttpFixturePreparationCancellationRecord, HttpFixturePreparationCancellationDeliveryRecord)),
])
def test_fixture_preparation_migration_has_exact_immutable_parents_without_backfill(module, models):
    migration = importlib.import_module("apps.api.migrations.versions." + module)
    assert len(migration.revision) <= 32
    tables = tuple(model.__table__ for model in models)
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_preparation_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert all(session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0 for table in tables)
            migration.downgrade()
            assert all(not inspect(connection).has_table(table.name, schema=namespace) for table in tables)
            migration.upgrade()
        for table in tables:
            assert len("immutable_" + table.name) <= 63
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
