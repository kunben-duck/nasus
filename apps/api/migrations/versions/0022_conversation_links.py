"""persist conversation relationships

Revision ID: 0022_conversation_links
Revises: 0021_swarm_runtime_controls
Create Date: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_conversation_links"
down_revision = "0021_swarm_runtime_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("left_conversation_id", sa.String(), nullable=False),
        sa.Column("right_conversation_id", sa.String(), nullable=False),
        sa.Column("link_kind", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_links_left_conversation_id",
        "conversation_links",
        ["left_conversation_id"],
    )
    op.create_index(
        "ix_conversation_links_right_conversation_id",
        "conversation_links",
        ["right_conversation_id"],
    )
    op.create_index(
        "ix_conversation_links_link_kind",
        "conversation_links",
        ["link_kind"],
    )
    op.create_index(
        "ix_conversation_links_created_at",
        "conversation_links",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_links_created_at",
        table_name="conversation_links",
    )
    op.drop_index(
        "ix_conversation_links_link_kind",
        table_name="conversation_links",
    )
    op.drop_index(
        "ix_conversation_links_right_conversation_id",
        table_name="conversation_links",
    )
    op.drop_index(
        "ix_conversation_links_left_conversation_id",
        table_name="conversation_links",
    )
    op.drop_table("conversation_links")
