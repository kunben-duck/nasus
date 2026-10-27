"""Rehearse empty 0110 only in an isolated schema of a disposable PG database."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.http_fixture_recipe_models import HttpFixtureRecipeRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_fixture_recipe_empty_roundtrip_matches_full_parent_and_immutable_schema():
    migration = importlib.import_module("apps.api.migrations.versions.0110_http_fixture_recipes")
    table = HttpFixtureRecipeRecord.__table__
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_recipe_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0
            migration.downgrade()
            assert not inspect(connection).has_table(table.name, schema=namespace)
            migration.upgrade()
        actual = inspect(connection)
        columns = actual.get_columns(table.name, schema=namespace)
        assert {column["name"] for column in columns} == set(table.columns.keys())
        assert {column["name"] for column in columns if column["nullable"]} == set()
        expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements))
            for fk in table.foreign_key_constraints}
        observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name
            for name in fk["referred_columns"])) for fk in actual.get_foreign_keys(table.name, schema=namespace)}
        assert observed == expected
        triggers = session.execute(text("""
            SELECT tgname FROM pg_trigger
            WHERE NOT tgisinternal AND tgrelid = CAST(:table AS regclass)
        """), {"table": namespace + "." + table.name}).scalars().all()
        assert triggers == ["immutable_quality_http_fixture_recipes"]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
