"""add agent memory items

Revision ID: 0012_agent_memory_items
Revises: 0011_user_avatar_object_storage
Create Date: 2026-06-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_agent_memory_items"
down_revision = "0011_user_avatar_object_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("memory_scope", sa.String(), nullable=False),
        sa.Column("owner_ref", sa.String(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("object_refs", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memory_items_memory_scope", "agent_memory_items", ["memory_scope"])
    op.create_index("ix_agent_memory_items_owner_ref", "agent_memory_items", ["owner_ref"])
    op.create_index("ix_agent_memory_items_status", "agent_memory_items", ["status"])
    op.create_index("ix_agent_memory_items_expires_at", "agent_memory_items", ["expires_at"])
    op.create_index("ix_agent_memory_items_created_at", "agent_memory_items", ["created_at"])

    op.create_table(
        "agent_memory_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("target_ref", sa.String(), nullable=False),
        sa.Column("link_kind", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memory_links_memory_id", "agent_memory_links", ["memory_id"])
    op.create_index("ix_agent_memory_links_target_ref", "agent_memory_links", ["target_ref"])
    op.create_index("ix_agent_memory_links_link_kind", "agent_memory_links", ["link_kind"])
    op.create_index("ix_agent_memory_links_created_at", "agent_memory_links", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_memory_links_created_at", table_name="agent_memory_links")
    op.drop_index("ix_agent_memory_links_link_kind", table_name="agent_memory_links")
    op.drop_index("ix_agent_memory_links_target_ref", table_name="agent_memory_links")
    op.drop_index("ix_agent_memory_links_memory_id", table_name="agent_memory_links")
    op.drop_table("agent_memory_links")

    op.drop_index("ix_agent_memory_items_created_at", table_name="agent_memory_items")
    op.drop_index("ix_agent_memory_items_expires_at", table_name="agent_memory_items")
    op.drop_index("ix_agent_memory_items_status", table_name="agent_memory_items")
    op.drop_index("ix_agent_memory_items_owner_ref", table_name="agent_memory_items")
    op.drop_index("ix_agent_memory_items_memory_scope", table_name="agent_memory_items")
    op.drop_table("agent_memory_items")
