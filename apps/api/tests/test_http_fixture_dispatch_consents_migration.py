"""Empty 0112 up/down/up in an isolated PostgreSQL schema, never developer data."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_dispatch_permission_empty_migration_has_both_original_worker_and_grant_fks():
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_dispatch_consent_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            for name in ("0108_http_fixture_journals", "0109_http_fixture_work", "0110_http_fixture_recipes", "0111_http_fixture_grants"):
                importlib.import_module("apps.api.migrations.versions." + name).upgrade()
            migration = importlib.import_module("apps.api.migrations.versions.0112_http_fixture_dispatch_consents")
            migration.upgrade()
            table = HttpFixtureDispatchConsentRecord.__table__
            assert session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0
            migration.downgrade()
            assert not inspect(connection).has_table(table.name, schema=namespace)
            migration.upgrade()
        schema = inspect(connection)
        assert {column["name"] for column in schema.get_columns(table.name, schema=namespace)} == set(table.columns.keys())
        assert not any(column["nullable"] for column in schema.get_columns(table.name, schema=namespace))
        expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements)) for fk in table.foreign_key_constraints}
        observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name for name in fk["referred_columns"]))
            for fk in schema.get_foreign_keys(table.name, schema=namespace)}
        assert observed == expected
        assert session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid=CAST(:table AS regclass)"),
            {"table": namespace + "." + table.name}).scalars().all() == ["immutable_quality_http_fixture_dispatch_consents"]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
