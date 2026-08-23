"""add durable SSE event outbox

Revision ID: 0016_sse_event_outbox
Revises: 0015_project_role_bindings
Create Date: 2026-07-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_sse_event_outbox"
down_revision = "0015_project_role_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sse_event_outbox",
        sa.Column("sequence", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("agent_goal_id", sa.String(), nullable=True),
        sa.Column("swarm_run_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("retention_until", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("event_id"),
    )
    for column_name in (
        "event_id",
        "event_type",
        "occurred_at",
        "conversation_id",
        "agent_goal_id",
        "swarm_run_id",
        "entity_type",
        "entity_id",
        "entity_version",
        "retention_until",
    ):
        op.create_index(
            f"ix_sse_event_outbox_{column_name}",
            "sse_event_outbox",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("sse_event_outbox")
