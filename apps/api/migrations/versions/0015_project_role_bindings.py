"""add project-scoped role bindings

Revision ID: 0015_project_role_bindings
Revises: 0014_embedding_vector_storage
Create Date: 2026-07-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_project_role_bindings"
down_revision = "0014_embedding_vector_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_identities",
        "role",
        existing_type=sa.String(),
        server_default="qa_lead",
        existing_nullable=False,
    )
    op.create_table(
        "project_role_bindings",
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("scope_ref", sa.String(), nullable=False),
        sa.Column("effective_policy_ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint("user_id", "scope_key", name="uq_project_role_binding_user_scope"),
    )
    for column_name in (
        "project_id",
        "version_id",
        "session_id",
        "user_id",
        "role",
        "scope_key",
        "status",
        "created_at",
        "updated_at",
        "created_by",
    ):
        op.create_index(
            f"ix_project_role_bindings_{column_name}",
            "project_role_bindings",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("project_role_bindings")
    op.alter_column(
        "user_identities",
        "role",
        existing_type=sa.String(),
        server_default="platform_admin",
        existing_nullable=False,
    )
