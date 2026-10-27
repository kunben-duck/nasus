"""Exercise an actual pre-0096 schema, not current ORM-created tables."""
import importlib
import os
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_preexisting_commands_are_marked_without_inventing_source_inputs(monkeypatch):
    database_url = os.getenv("NASUS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("isolated PostgreSQL migration test requires NASUS_TEST_DATABASE_URL")
    url = make_url(database_url)
    assert url.get_backend_name() == "postgresql" and url.database.startswith("nasus_test_")
    admin = create_engine(url)
    schema = "materialization_migration_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE projects (id varchar PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE user_identities (user_id varchar PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE tool_invocations (id varchar PRIMARY KEY, tool_id varchar NOT NULL, status varchar NOT NULL, summary varchar NOT NULL)"))
            conn.execute(text("CREATE TABLE source_manifests (manifest_id varchar PRIMARY KEY, project_id varchar NOT NULL, UNIQUE(project_id, manifest_id))"))
            conn.execute(text("CREATE FUNCTION nasus_reject_image_revision_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'immutable' USING ERRCODE = '23514'; END; $$ LANGUAGE plpgsql"))
            conn.execute(text("INSERT INTO tool_invocations VALUES ('old-running', 'system_image.context.materialize', 'running', 'original'), "
                "('old-completed', 'system_image.baseline.initialize', 'completed', 'original-result'), "
                "('unrelated', 'query.answer', 'completed', 'unchanged')"))
            old = conn.execute(text("SELECT id, tool_id, status, summary FROM tool_invocations ORDER BY id")).all()
            migration = importlib.import_module("apps.api.migrations.versions.0096_materialization_inputs")
            with monkeypatch.context() as patch:
                patch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
                migration.upgrade()
                assert conn.execute(text("SELECT invocation_id FROM materialization_legacy_commands ORDER BY invocation_id")).scalars().all() == ["old-completed", "old-running"]
                assert conn.scalar(text("SELECT count(*) FROM materialization_source_inputs")) == 0
                assert conn.scalar(text("SELECT count(*) FROM tool_invocations WHERE materialization_input_hash IS NOT NULL")) == 0
                assert conn.execute(text("SELECT id, tool_id, status, summary FROM tool_invocations ORDER BY id")).all() == old
                migration.downgrade()
                assert conn.execute(text("SELECT id, tool_id, status, summary FROM tool_invocations ORDER BY id")).all() == old
                migration.upgrade()
                conn.execute(text("INSERT INTO tool_invocations VALUES ('new-command', 'system_image.context.materialize', 'running', 'new', NULL)"))
                assert conn.scalar(text("SELECT count(*) FROM materialization_legacy_commands WHERE invocation_id = 'new-command'")) == 0
                conn.execute(text("INSERT INTO projects VALUES ('project')"))
                conn.execute(text("INSERT INTO user_identities VALUES ('actor')"))
                conn.execute(text("INSERT INTO source_manifests VALUES ('manifest', 'project')"))
                conn.execute(text("INSERT INTO materialization_source_inputs VALUES ('new-command', 'project', 'actor', :hash, 'manifest', :hash, :hash, CURRENT_TIMESTAMP)"),
                    {"hash": "sha256:" + "0" * 64})
                with pytest.raises(RuntimeError, match="populated"):
                    migration.downgrade()
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
