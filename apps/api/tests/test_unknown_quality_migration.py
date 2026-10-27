"""Verify unknown values and historical scores on an actual old PG schema."""
import importlib
import os
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_unknown_quality_migration_preserves_history_and_refuses_lossy_downgrade(monkeypatch):
    database_url = os.getenv("NASUS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires isolated PostgreSQL migration runner")
    url = make_url(database_url)
    assert url.get_backend_name() == "postgresql" and url.database.startswith("nasus_test_")
    admin = create_engine(url)
    schema = "unknown_quality_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE quality_profiles (id varchar PRIMARY KEY, "
                "risk_score integer NOT NULL, coverage_score integer NOT NULL, release_score integer NOT NULL, "
                "automation_feasibility integer NOT NULL, confidence float NOT NULL)"))
            conn.execute(text("CREATE TABLE task_contexts (id varchar PRIMARY KEY, confidence float NOT NULL)"))
            conn.execute(text("INSERT INTO quality_profiles VALUES ('historical', 83, 65, 39, 56, .85), "
                "('measured-zero', 0, 0, 0, 0, 0)"))
            conn.execute(text("INSERT INTO task_contexts VALUES ('historical', .85), ('measured-zero', 0)"))
            old_profiles = conn.execute(text("SELECT * FROM quality_profiles ORDER BY id")).all()
            old_contexts = conn.execute(text("SELECT * FROM task_contexts ORDER BY id")).all()
            migration = importlib.import_module("apps.api.migrations.versions.0097_unknown_quality_scores")
            with monkeypatch.context() as patch:
                patch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
                migration.upgrade()
                assert conn.execute(text("SELECT * FROM quality_profiles ORDER BY id")).all() == old_profiles
                assert conn.execute(text("SELECT * FROM task_contexts ORDER BY id")).all() == old_contexts
                conn.execute(text("INSERT INTO quality_profiles VALUES ('unknown', NULL, NULL, NULL, NULL, NULL)"))
                with pytest.raises(RuntimeError, match="invented scores"):
                    migration.downgrade()
                assert conn.execute(text("SELECT * FROM quality_profiles WHERE id = 'unknown'")).one() == (
                    "unknown", None, None, None, None, None)
                conn.execute(text("DELETE FROM quality_profiles WHERE id = 'unknown'"))
                conn.execute(text("INSERT INTO task_contexts VALUES ('unknown', NULL)"))
                with pytest.raises(RuntimeError, match="invented scores"):
                    migration.downgrade()
                conn.execute(text("DELETE FROM task_contexts WHERE id = 'unknown'"))
                migration.downgrade()
                nullable = conn.execute(text("SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :schema AND column_name = 'confidence'"), {"schema": schema}).scalars().all()
                assert nullable == ["NO", "NO"]
                assert conn.execute(text("SELECT * FROM quality_profiles ORDER BY id")).all() == old_profiles
                assert conn.execute(text("SELECT * FROM task_contexts ORDER BY id")).all() == old_contexts
                migration.upgrade()
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
