"""add model provider configuration tables

Revision ID: 0007_model_provider_configs
Revises: 0006_agent_swarm_tables
Create Date: 2026-06-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_model_provider_configs"
down_revision = "0006_agent_swarm_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_provider_configs",
        sa.Column("config_id", sa.String(), primary_key=True),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("provider_kind", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_key_masked", sa.String(), nullable=True),
        sa.Column("last_tested_at", sa.String(), nullable=False),
        sa.Column("last_test_signature", sa.String(), nullable=False),
        sa.Column("last_test_result", sa.JSON(), nullable=False),
        sa.Column("legacy_imported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_model_provider_configs_route", "model_provider_configs", ["route"])
    op.create_index("ix_model_provider_configs_last_tested_at", "model_provider_configs", ["last_tested_at"])
    op.create_index("ix_model_provider_configs_last_test_signature", "model_provider_configs", ["last_test_signature"])
    op.create_index("ix_model_provider_configs_created_at", "model_provider_configs", ["created_at"])
    op.create_index("ix_model_provider_configs_updated_at", "model_provider_configs", ["updated_at"])

    op.create_table(
        "model_route_selections",
        sa.Column("route", sa.String(), primary_key=True),
        sa.Column("active_source", sa.String(), nullable=False),
        sa.Column("active_config_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_model_route_selections_active_config_id", "model_route_selections", ["active_config_id"])


def downgrade() -> None:
    op.drop_index("ix_model_route_selections_active_config_id", table_name="model_route_selections")
    op.drop_table("model_route_selections")

    op.drop_index("ix_model_provider_configs_updated_at", table_name="model_provider_configs")
    op.drop_index("ix_model_provider_configs_created_at", table_name="model_provider_configs")
    op.drop_index("ix_model_provider_configs_last_test_signature", table_name="model_provider_configs")
    op.drop_index("ix_model_provider_configs_last_tested_at", table_name="model_provider_configs")
    op.drop_index("ix_model_provider_configs_route", table_name="model_provider_configs")
    op.drop_table("model_provider_configs")
