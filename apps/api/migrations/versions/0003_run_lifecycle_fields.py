"""add run lifecycle fields

Revision ID: 0003_run_lifecycle
Revises: 0002_system_quality
Create Date: 2026-06-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_run_lifecycle"
down_revision = "0002_system_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("task_context_id", sa.String(), nullable=True))
    op.add_column("runs", sa.Column("runner_job_id", sa.String(), nullable=True))
    op.add_column("runs", sa.Column("healing_depth", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("last_failure_fingerprint", sa.String(), nullable=True))
    op.create_index("ix_runs_task_context_id", "runs", ["task_context_id"])
    op.create_index("ix_runs_runner_job_id", "runs", ["runner_job_id"])
    op.create_index("ix_runs_last_failure_fingerprint", "runs", ["last_failure_fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_runs_last_failure_fingerprint", table_name="runs")
    op.drop_index("ix_runs_runner_job_id", table_name="runs")
    op.drop_index("ix_runs_task_context_id", table_name="runs")
    op.drop_column("runs", "last_failure_fingerprint")
    op.drop_column("runs", "healing_depth")
    op.drop_column("runs", "runner_job_id")
    op.drop_column("runs", "task_context_id")
