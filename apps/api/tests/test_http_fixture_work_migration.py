"""Empty-schema PG roundtrip, not populated execution or business evidence."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.http_fixture_work_models import (
    HttpFixtureWorkLeaseRecord, HttpFixtureDispatchOwnershipRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_private_fixture_work_schema_empty_roundtrip_matches_models_and_guards():
    migration = importlib.import_module("apps.api.migrations.versions.0109_http_fixture_work")
    tables = (HttpFixtureWorkLeaseRecord.__table__, HttpFixtureDispatchOwnershipRecord.__table__)
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_work_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        guard = namespace + ".nasus_guard_http_fixture_work()"
        with Operations.context(MigrationContext.configure(connection)):
            # The full suite can already have original public journal rows.
            # Rehearse only this test's schema, never downgrade that history.
            migration.upgrade()
            assert all(session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0 for table in tables)
            migration.downgrade()
            assert all(not inspect(connection).has_table(table.name, schema=namespace) for table in tables)
            assert session.scalar(text("SELECT to_regprocedure(:guard)"), {"guard": guard}) is None
            migration.upgrade()
        for table in tables:
            actual = inspect(connection)
            columns = actual.get_columns(table.name, schema=namespace)
            assert {item["name"] for item in columns} == set(table.columns.keys())
            assert {item["name"] for item in columns if item["nullable"]} == set()
            expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements))
                for fk in table.foreign_key_constraints}
            observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name
                for name in fk["referred_columns"])) for fk in actual.get_foreign_keys(table.name, schema=namespace)}
            assert observed == expected
        triggers = session.execute(text("""
            SELECT tgname FROM pg_trigger
            WHERE NOT tgisinternal AND tgrelid IN
                (CAST(:leases AS regclass), CAST(:ownership AS regclass))
            ORDER BY tgname
        """), {"leases": namespace + ".quality_http_fixture_work_leases",
            "ownership": namespace + ".quality_http_fixture_dispatch_ownership"}).scalars().all()
        assert triggers == ["guarded_quality_http_fixture_work_leases", "immutable_quality_http_fixture_dispatch_ownership"]
        assert session.scalar(text("SELECT to_regprocedure(:guard)"), {"guard": guard}) is not None
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
