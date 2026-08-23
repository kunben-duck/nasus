"""add durable model configuration test grants

Revision ID: 0020_model_config_test_grants
Revises: 0019_agent_goal_runtime_budgets
Create Date: 2026-07-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_model_config_test_grants"
down_revision = "0019_agent_goal_runtime_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_config_test_grants",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("config_id", sa.String(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_model_config_test_grants_route",
        "model_config_test_grants",
        ["route"],
    )
    op.create_index(
        "ix_model_config_test_grants_config_id",
        "model_config_test_grants",
        ["config_id"],
    )
    op.create_index(
        "ix_model_config_test_grants_expires_at",
        "model_config_test_grants",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_config_test_grants_expires_at",
        table_name="model_config_test_grants",
    )
    op.drop_index(
        "ix_model_config_test_grants_config_id",
        table_name="model_config_test_grants",
    )
    op.drop_index(
        "ix_model_config_test_grants_route",
        table_name="model_config_test_grants",
    )
    op.drop_table("model_config_test_grants")
