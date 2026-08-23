"""add durable AgentGoal runtime budgets

Revision ID: 0019_agent_goal_runtime_budgets
Revises: 0018_release_readiness_evidence
Create Date: 2026-07-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_agent_goal_runtime_budgets"
down_revision = "0018_release_readiness_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    integer_columns = (
        ("max_model_calls", 32),
        ("max_thinking_tokens", 500_000),
        ("max_runtime_seconds", 1_800),
        ("max_no_progress_observations", 3),
        ("model_calls_used", 0),
        ("thinking_input_tokens_used", 0),
        ("thinking_output_tokens_used", 0),
        ("thinking_tokens_used", 0),
        ("no_progress_observations", 0),
    )
    for name, default in integer_columns:
        op.add_column(
            "agent_goals",
            sa.Column(
                name,
                sa.Integer(),
                server_default=sa.text(str(default)),
                nullable=False,
            ),
        )
    op.add_column("agent_goals", sa.Column("started_at", sa.String(), nullable=True))
    op.add_column("agent_goals", sa.Column("last_progress_at", sa.String(), nullable=True))
    op.add_column(
        "agent_goals",
        sa.Column("last_progress_fingerprint", sa.String(), nullable=True),
    )
    op.add_column(
        "agent_goals",
        sa.Column("budget_exhausted_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_agent_goals_started_at", "agent_goals", ["started_at"])
    op.create_index(
        "ix_agent_goals_last_progress_at",
        "agent_goals",
        ["last_progress_at"],
    )
    op.create_index(
        "ix_agent_goals_budget_exhausted_reason",
        "agent_goals",
        ["budget_exhausted_reason"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_goals_budget_exhausted_reason",
        table_name="agent_goals",
    )
    op.drop_index("ix_agent_goals_last_progress_at", table_name="agent_goals")
    op.drop_index("ix_agent_goals_started_at", table_name="agent_goals")
    for name in (
        "budget_exhausted_reason",
        "last_progress_fingerprint",
        "last_progress_at",
        "started_at",
        "no_progress_observations",
        "thinking_tokens_used",
        "thinking_output_tokens_used",
        "thinking_input_tokens_used",
        "model_calls_used",
        "max_no_progress_observations",
        "max_runtime_seconds",
        "max_thinking_tokens",
        "max_model_calls",
    ):
        op.drop_column("agent_goals", name)
