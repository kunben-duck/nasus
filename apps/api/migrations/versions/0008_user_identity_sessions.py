"""add user identity and access session tables

Revision ID: 0008_user_identity_sessions
Revises: 0007_model_provider_configs
Create Date: 2026-06-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_user_identity_sessions"
down_revision = "0007_model_provider_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="platform_admin"),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("last_login_at", sa.String(), nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_user_identities_email", "user_identities", ["email"])
    op.create_index("ix_user_identities_role", "user_identities", ["role"])
    op.create_index("ix_user_identities_status", "user_identities", ["status"])
    op.create_index("ix_user_identities_created_at", "user_identities", ["created_at"])
    op.create_index("ix_user_identities_updated_at", "user_identities", ["updated_at"])
    op.create_index("ix_user_identities_last_login_at", "user_identities", ["last_login_at"])

    op.create_table(
        "access_sessions",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.Column("last_seen_at", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_access_sessions_user_id", "access_sessions", ["user_id"])
    op.create_index("ix_access_sessions_token_hash", "access_sessions", ["token_hash"])
    op.create_index("ix_access_sessions_status", "access_sessions", ["status"])
    op.create_index("ix_access_sessions_created_at", "access_sessions", ["created_at"])
    op.create_index("ix_access_sessions_expires_at", "access_sessions", ["expires_at"])
    op.create_index("ix_access_sessions_revoked_at", "access_sessions", ["revoked_at"])
    op.create_index("ix_access_sessions_last_seen_at", "access_sessions", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_access_sessions_last_seen_at", table_name="access_sessions")
    op.drop_index("ix_access_sessions_revoked_at", table_name="access_sessions")
    op.drop_index("ix_access_sessions_expires_at", table_name="access_sessions")
    op.drop_index("ix_access_sessions_created_at", table_name="access_sessions")
    op.drop_index("ix_access_sessions_status", table_name="access_sessions")
    op.drop_index("ix_access_sessions_token_hash", table_name="access_sessions")
    op.drop_index("ix_access_sessions_user_id", table_name="access_sessions")
    op.drop_table("access_sessions")

    op.drop_index("ix_user_identities_last_login_at", table_name="user_identities")
    op.drop_index("ix_user_identities_updated_at", table_name="user_identities")
    op.drop_index("ix_user_identities_created_at", table_name="user_identities")
    op.drop_index("ix_user_identities_status", table_name="user_identities")
    op.drop_index("ix_user_identities_role", table_name="user_identities")
    op.drop_index("ix_user_identities_email", table_name="user_identities")
    op.drop_table("user_identities")
