from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_sqlite_path() -> Path:
    state_dir = Path(os.getenv("NASUS_STATE_DIR", _repo_root() / ".nasus" / "state"))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "nasus.db"


DATABASE_URL = os.getenv("NASUS_DATABASE_URL", f"sqlite+pysqlite:///{_default_sqlite_path()}")
AUTO_CREATE_TABLES = os.getenv("NASUS_AUTO_CREATE_TABLES", "true").lower() not in {"0", "false", "no"}

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()


def get_database_url() -> str:
    return DATABASE_URL


def init_database() -> None:
    from . import db_models  # noqa: F401

    if not AUTO_CREATE_TABLES:
        return

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_additive_schema()


def _ensure_sqlite_additive_schema() -> None:
    """Apply safe additive fixes for local SQLite state files.

    Production PostgreSQL schema is owned by Alembic. Local development uses
    AUTO_CREATE_TABLES for convenience, but SQLAlchemy create_all does not add
    columns to existing SQLite tables. Keep this narrow and additive only.
    """

    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "user_identities" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE user_identities (
                        user_id VARCHAR NOT NULL PRIMARY KEY,
                        email VARCHAR NOT NULL UNIQUE,
                        display_name VARCHAR NOT NULL,
                        role VARCHAR NOT NULL DEFAULT 'platform_admin',
                        password_hash TEXT NOT NULL,
                        status VARCHAR NOT NULL DEFAULT 'active',
                        avatar_url TEXT,
                        avatar_preset VARCHAR,
                        avatar_object_ref TEXT,
                        avatar_mime_type VARCHAR,
                        created_at VARCHAR NOT NULL,
                        updated_at VARCHAR NOT NULL,
                        last_login_at VARCHAR
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX ix_user_identities_email ON user_identities (email)"))
            connection.execute(text("CREATE INDEX ix_user_identities_role ON user_identities (role)"))
            connection.execute(text("CREATE INDEX ix_user_identities_status ON user_identities (status)"))
            connection.execute(text("CREATE INDEX ix_user_identities_created_at ON user_identities (created_at)"))
            connection.execute(text("CREATE INDEX ix_user_identities_updated_at ON user_identities (updated_at)"))
            connection.execute(text("CREATE INDEX ix_user_identities_last_login_at ON user_identities (last_login_at)"))
            connection.execute(text("CREATE INDEX ix_user_identities_avatar_preset ON user_identities (avatar_preset)"))
        elif "user_identities" in table_names:
            user_columns = {column["name"] for column in inspector.get_columns("user_identities")}
            if "avatar_url" not in user_columns:
                connection.execute(text("ALTER TABLE user_identities ADD COLUMN avatar_url TEXT"))
            if "avatar_preset" not in user_columns:
                connection.execute(text("ALTER TABLE user_identities ADD COLUMN avatar_preset VARCHAR"))
                connection.execute(text("CREATE INDEX ix_user_identities_avatar_preset ON user_identities (avatar_preset)"))
            if "avatar_object_ref" not in user_columns:
                connection.execute(text("ALTER TABLE user_identities ADD COLUMN avatar_object_ref TEXT"))
            if "avatar_mime_type" not in user_columns:
                connection.execute(text("ALTER TABLE user_identities ADD COLUMN avatar_mime_type VARCHAR"))

        if "access_sessions" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE access_sessions (
                        session_id VARCHAR NOT NULL PRIMARY KEY,
                        user_id VARCHAR NOT NULL,
                        token_hash VARCHAR NOT NULL UNIQUE,
                        status VARCHAR NOT NULL DEFAULT 'active',
                        created_at VARCHAR NOT NULL,
                        expires_at VARCHAR NOT NULL,
                        revoked_at VARCHAR,
                        last_seen_at VARCHAR,
                        user_agent VARCHAR
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX ix_access_sessions_user_id ON access_sessions (user_id)"))
            connection.execute(text("CREATE INDEX ix_access_sessions_token_hash ON access_sessions (token_hash)"))
            connection.execute(text("CREATE INDEX ix_access_sessions_status ON access_sessions (status)"))
            connection.execute(text("CREATE INDEX ix_access_sessions_created_at ON access_sessions (created_at)"))
            connection.execute(text("CREATE INDEX ix_access_sessions_expires_at ON access_sessions (expires_at)"))
            connection.execute(text("CREATE INDEX ix_access_sessions_revoked_at ON access_sessions (revoked_at)"))
            connection.execute(text("CREATE INDEX ix_access_sessions_last_seen_at ON access_sessions (last_seen_at)"))

        if "retrieval_runs" in table_names:
            retrieval_columns = {column["name"] for column in inspector.get_columns("retrieval_runs")}
            if "embedding_record_ids" not in retrieval_columns:
                connection.execute(
                    text("ALTER TABLE retrieval_runs ADD COLUMN embedding_record_ids JSON NOT NULL DEFAULT '[]'")
                )

        if "embedding_records" in table_names:
            embedding_columns = {column["name"] for column in inspector.get_columns("embedding_records")}
            if "chunk_ref" not in embedding_columns:
                connection.execute(text("ALTER TABLE embedding_records ADD COLUMN chunk_ref VARCHAR"))
            if "embedding_vector" not in embedding_columns:
                connection.execute(text("ALTER TABLE embedding_records ADD COLUMN embedding_vector JSON"))
            if "search_text" not in embedding_columns:
                connection.execute(text("ALTER TABLE embedding_records ADD COLUMN search_text TEXT NOT NULL DEFAULT ''"))

        if "runs" in table_names:
            run_columns = {column["name"] for column in inspector.get_columns("runs")}
            run_additive_columns = {
                "task_context_id": "VARCHAR",
                "runner_job_id": "VARCHAR",
                "healing_depth": "INTEGER NOT NULL DEFAULT 0",
                "last_failure_fingerprint": "VARCHAR",
            }
            for column_name, column_type in run_additive_columns.items():
                if column_name not in run_columns:
                    connection.execute(text(f"ALTER TABLE runs ADD COLUMN {column_name} {column_type}"))

        if "release_readiness" in table_names:
            release_readiness_columns = {
                column["name"]
                for column in inspector.get_columns("release_readiness")
            }
            release_readiness_additive_columns = {
                "score_breakdown": "JSON NOT NULL DEFAULT '{}'",
                "evidence_summary": "JSON NOT NULL DEFAULT '{}'",
            }
            for column_name, column_type in release_readiness_additive_columns.items():
                if column_name not in release_readiness_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE release_readiness "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )

        if "agent_goals" in table_names:
            agent_goal_columns = {column["name"] for column in inspector.get_columns("agent_goals")}
            agent_goal_additive_columns = {
                "goal_template": "VARCHAR",
                "goal_description": "VARCHAR",
                "target_refs": "JSON NOT NULL DEFAULT '[]'",
                "query_keys": "JSON NOT NULL DEFAULT '[]'",
                "planner_kind": "VARCHAR",
                "planning_summary": "VARCHAR",
                "max_model_calls": "INTEGER NOT NULL DEFAULT 32",
                "max_thinking_tokens": "INTEGER NOT NULL DEFAULT 500000",
                "max_runtime_seconds": "INTEGER NOT NULL DEFAULT 1800",
                "max_no_progress_observations": "INTEGER NOT NULL DEFAULT 3",
                "model_calls_used": "INTEGER NOT NULL DEFAULT 0",
                "thinking_input_tokens_used": "INTEGER NOT NULL DEFAULT 0",
                "thinking_output_tokens_used": "INTEGER NOT NULL DEFAULT 0",
                "thinking_tokens_used": "INTEGER NOT NULL DEFAULT 0",
                "no_progress_observations": "INTEGER NOT NULL DEFAULT 0",
                "started_at": "VARCHAR",
                "last_progress_at": "VARCHAR",
                "last_progress_fingerprint": "VARCHAR",
                "budget_exhausted_reason": "VARCHAR",
            }
            for column_name, column_type in agent_goal_additive_columns.items():
                if column_name not in agent_goal_columns:
                    connection.execute(text(f"ALTER TABLE agent_goals ADD COLUMN {column_name} {column_type}"))
            indexed_columns = {index["name"] for index in inspector.get_indexes("agent_goals")}
            if "ix_agent_goals_goal_template" not in indexed_columns:
                connection.execute(text("CREATE INDEX ix_agent_goals_goal_template ON agent_goals (goal_template)"))
            if "ix_agent_goals_planner_kind" not in indexed_columns:
                connection.execute(text("CREATE INDEX ix_agent_goals_planner_kind ON agent_goals (planner_kind)"))
            if "ix_agent_goals_started_at" not in indexed_columns:
                connection.execute(text("CREATE INDEX ix_agent_goals_started_at ON agent_goals (started_at)"))
            if "ix_agent_goals_last_progress_at" not in indexed_columns:
                connection.execute(
                    text("CREATE INDEX ix_agent_goals_last_progress_at ON agent_goals (last_progress_at)")
                )
            if "ix_agent_goals_budget_exhausted_reason" not in indexed_columns:
                connection.execute(
                    text(
                        "CREATE INDEX ix_agent_goals_budget_exhausted_reason "
                        "ON agent_goals (budget_exhausted_reason)"
                    )
                )

        if "tool_invocations" in table_names:
            invocation_columns = {
                column["name"]
                for column in inspector.get_columns("tool_invocations")
            }
            invocation_additive_columns = {
                "idempotency_scope": "VARCHAR",
                "idempotency_key": "VARCHAR",
                "idempotency_fingerprint": "VARCHAR",
                "revision": "INTEGER NOT NULL DEFAULT 0",
            }
            for column_name, column_type in invocation_additive_columns.items():
                if column_name not in invocation_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE tool_invocations "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_tool_invocations_idempotency_scope "
                    "ON tool_invocations (idempotency_scope)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_tool_invocations_idempotency_key "
                    "ON tool_invocations (idempotency_key)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_tool_invocation_idempotency "
                    "ON tool_invocations "
                    "(idempotency_scope, tool_id, idempotency_key)"
                )
            )

        if "agent_memory_items" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE agent_memory_items (
                        id VARCHAR NOT NULL PRIMARY KEY,
                        memory_scope VARCHAR NOT NULL,
                        owner_ref VARCHAR NOT NULL,
                        source_refs JSON NOT NULL DEFAULT '[]',
                        summary TEXT NOT NULL,
                        object_refs JSON NOT NULL DEFAULT '[]',
                        evidence_refs JSON NOT NULL DEFAULT '[]',
                        status VARCHAR NOT NULL DEFAULT 'active',
                        expires_at VARCHAR,
                        created_at VARCHAR NOT NULL
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX ix_agent_memory_items_memory_scope ON agent_memory_items (memory_scope)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_items_owner_ref ON agent_memory_items (owner_ref)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_items_status ON agent_memory_items (status)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_items_expires_at ON agent_memory_items (expires_at)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_items_created_at ON agent_memory_items (created_at)"))

        if "agent_memory_links" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE agent_memory_links (
                        id VARCHAR NOT NULL PRIMARY KEY,
                        memory_id VARCHAR NOT NULL,
                        target_ref VARCHAR NOT NULL,
                        link_kind VARCHAR NOT NULL,
                        confidence FLOAT NOT NULL DEFAULT 0,
                        created_at VARCHAR NOT NULL
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX ix_agent_memory_links_memory_id ON agent_memory_links (memory_id)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_links_target_ref ON agent_memory_links (target_ref)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_links_link_kind ON agent_memory_links (link_kind)"))
            connection.execute(text("CREATE INDEX ix_agent_memory_links_created_at ON agent_memory_links (created_at)"))
