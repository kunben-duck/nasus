"""persist immutable run retry context

Revision ID: 0028_run_retry_context
Revises: 0027_prompt_registry
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0028_run_retry_context"
down_revision: Union[str, None] = "0027_prompt_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("us_id", sa.String(), nullable=True))
    op.add_column("runs", sa.Column("target_base_url", sa.String(), nullable=True))
    op.add_column("runs", sa.Column("automation_asset_ref", sa.String(), nullable=True))
    op.add_column("runs", sa.Column("automation_script_id", sa.String(), nullable=True))
    op.add_column(
        "runs",
        sa.Column("execution_plan", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "runs",
        sa.Column("execution_timeout_ms", sa.Integer(), nullable=False, server_default="60000"),
    )
    op.add_column("runs", sa.Column("retry_of_run_id", sa.String(), nullable=True))
    op.add_column(
        "runs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_runs_us_id", "runs", ["us_id"])
    op.create_index("ix_runs_automation_asset_ref", "runs", ["automation_asset_ref"])
    op.create_index("ix_runs_automation_script_id", "runs", ["automation_script_id"])
    op.create_index("ix_runs_retry_of_run_id", "runs", ["retry_of_run_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_retry_of_run_id", table_name="runs")
    op.drop_index("ix_runs_automation_script_id", table_name="runs")
    op.drop_index("ix_runs_automation_asset_ref", table_name="runs")
    op.drop_index("ix_runs_us_id", table_name="runs")
    op.drop_column("runs", "attempt")
    op.drop_column("runs", "retry_of_run_id")
    op.drop_column("runs", "execution_timeout_ms")
    op.drop_column("runs", "execution_plan")
    op.drop_column("runs", "automation_script_id")
    op.drop_column("runs", "automation_asset_ref")
    op.drop_column("runs", "target_base_url")
    op.drop_column("runs", "us_id")
