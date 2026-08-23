"""add agent swarm tables

Revision ID: 0006_agent_swarm_tables
Revises: 0005_audit_events
Create Date: 2026-06-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_agent_swarm_tables"
down_revision = "0005_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_swarm_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("parent_goal_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("swarm_kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("max_parallel_agents", sa.Integer(), nullable=False),
        sa.Column("merge_strategy", sa.String(), nullable=False),
        sa.Column("target_refs", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
    )
    op.create_index("ix_agent_swarm_runs_parent_goal_id", "agent_swarm_runs", ["parent_goal_id"])
    op.create_index("ix_agent_swarm_runs_conversation_id", "agent_swarm_runs", ["conversation_id"])
    op.create_index("ix_agent_swarm_runs_swarm_kind", "agent_swarm_runs", ["swarm_kind"])
    op.create_index("ix_agent_swarm_runs_status", "agent_swarm_runs", ["status"])
    op.create_index("ix_agent_swarm_runs_created_at", "agent_swarm_runs", ["created_at"])

    op.create_table(
        "agent_worker_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("swarm_run_id", sa.String(), nullable=False),
        sa.Column("worker_agent_kind", sa.String(), nullable=False),
        sa.Column("target_refs", sa.JSON(), nullable=False),
        sa.Column("input_context_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("agent_goal_id", sa.String(), nullable=True),
        sa.Column("tool_invocation_refs", sa.JSON(), nullable=False),
        sa.Column("candidate_result_ref", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
    )
    op.create_index("ix_agent_worker_assignments_swarm_run_id", "agent_worker_assignments", ["swarm_run_id"])
    op.create_index("ix_agent_worker_assignments_worker_agent_kind", "agent_worker_assignments", ["worker_agent_kind"])
    op.create_index("ix_agent_worker_assignments_status", "agent_worker_assignments", ["status"])
    op.create_index("ix_agent_worker_assignments_agent_goal_id", "agent_worker_assignments", ["agent_goal_id"])
    op.create_index("ix_agent_worker_assignments_created_at", "agent_worker_assignments", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_worker_assignments_created_at", table_name="agent_worker_assignments")
    op.drop_index("ix_agent_worker_assignments_agent_goal_id", table_name="agent_worker_assignments")
    op.drop_index("ix_agent_worker_assignments_status", table_name="agent_worker_assignments")
    op.drop_index("ix_agent_worker_assignments_worker_agent_kind", table_name="agent_worker_assignments")
    op.drop_index("ix_agent_worker_assignments_swarm_run_id", table_name="agent_worker_assignments")
    op.drop_table("agent_worker_assignments")

    op.drop_index("ix_agent_swarm_runs_created_at", table_name="agent_swarm_runs")
    op.drop_index("ix_agent_swarm_runs_status", table_name="agent_swarm_runs")
    op.drop_index("ix_agent_swarm_runs_swarm_kind", table_name="agent_swarm_runs")
    op.drop_index("ix_agent_swarm_runs_conversation_id", table_name="agent_swarm_runs")
    op.drop_index("ix_agent_swarm_runs_parent_goal_id", table_name="agent_swarm_runs")
    op.drop_table("agent_swarm_runs")
