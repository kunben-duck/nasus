"""add agent goal planning facts

Revision ID: 0013_agent_goal_planning_facts
Revises: 0012_agent_memory_items
Create Date: 2026-06-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_agent_goal_planning_facts"
down_revision = "0012_agent_memory_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_goals", sa.Column("goal_template", sa.String(), nullable=True))
    op.add_column("agent_goals", sa.Column("goal_description", sa.String(), nullable=True))
    op.add_column("agent_goals", sa.Column("target_refs", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("agent_goals", sa.Column("query_keys", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("agent_goals", sa.Column("planner_kind", sa.String(), nullable=True))
    op.add_column("agent_goals", sa.Column("planning_summary", sa.String(), nullable=True))
    op.create_index("ix_agent_goals_goal_template", "agent_goals", ["goal_template"])
    op.create_index("ix_agent_goals_planner_kind", "agent_goals", ["planner_kind"])


def downgrade() -> None:
    op.drop_index("ix_agent_goals_planner_kind", table_name="agent_goals")
    op.drop_index("ix_agent_goals_goal_template", table_name="agent_goals")
    op.drop_column("agent_goals", "planning_summary")
    op.drop_column("agent_goals", "planner_kind")
    op.drop_column("agent_goals", "query_keys")
    op.drop_column("agent_goals", "target_refs")
    op.drop_column("agent_goals", "goal_description")
    op.drop_column("agent_goals", "goal_template")
