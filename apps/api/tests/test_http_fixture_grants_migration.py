"""Empty consent migration rehearsal in a disposable PostgreSQL schema only."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_independent_consent_empty_roundtrip_has_original_recipe_fk_and_no_backfill():
    recipes = importlib.import_module("apps.api.migrations.versions.0110_http_fixture_recipes")
    grants = importlib.import_module("apps.api.migrations.versions.0111_http_fixture_grants")
    table = HttpFixtureGrantRecord.__table__
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_grant_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            recipes.upgrade()
            grants.upgrade()
            assert session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0
            grants.downgrade()
            assert not inspect(connection).has_table(table.name, schema=namespace)
            grants.upgrade()
        actual = inspect(connection)
        assert {column["name"] for column in actual.get_columns(table.name, schema=namespace)} == set(table.columns.keys())
        assert not any(column["nullable"] for column in actual.get_columns(table.name, schema=namespace))
        expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements)) for fk in table.foreign_key_constraints}
        observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name for name in fk["referred_columns"]))
            for fk in actual.get_foreign_keys(table.name, schema=namespace)}
        assert observed == expected
        assert session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid=CAST(:table AS regclass)"),
            {"table": namespace + "." + table.name}).scalars().all() == ["immutable_quality_http_fixture_grants"]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
