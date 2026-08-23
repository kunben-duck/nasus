"""add agent swarm runtime controls

Revision ID: 0021_swarm_runtime_controls
Revises: 0020_model_config_test_grants
Create Date: 2026-07-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_swarm_runtime_controls"
down_revision = "0020_model_config_test_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_swarm_runs",
        sa.Column("budget_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "agent_worker_assignments",
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )
    op.alter_column(
        "agent_worker_assignments",
        "timeout_seconds",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("agent_worker_assignments", "timeout_seconds")
    op.drop_column("agent_swarm_runs", "budget_ref")
