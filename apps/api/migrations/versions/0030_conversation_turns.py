"""add durable asynchronous conversation turns

Revision ID: 0030_conversation_turns
Revises: 0029_agent_planner_prompt
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0030_conversation_turns"
down_revision: Union[str, None] = "0029_agent_planner_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("user_message_id", sa.String(), nullable=False),
        sa.Column("assistant_message_id", sa.String(), nullable=True),
        sa.Column("workflow_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="accepted"),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "idempotency_key", name="uq_conversation_turn_idempotency"),
        sa.UniqueConstraint("workflow_id"),
    )
    for column in (
        "conversation_id",
        "user_message_id",
        "assistant_message_id",
        "workflow_id",
        "idempotency_key",
        "status",
        "created_at",
        "updated_at",
        "completed_at",
    ):
        op.create_index(f"ix_conversation_turns_{column}", "conversation_turns", [column])
    op.create_index(
        "uq_conversation_turn_active",
        "conversation_turns",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('accepted', 'planning', 'streaming', 'delegated')"
        ),
        sqlite_where=sa.text(
            "status IN ('accepted', 'planning', 'streaming', 'delegated')"
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_turns")
