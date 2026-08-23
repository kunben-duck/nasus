"""persist governed structured merge resolutions

Revision ID: 0023_merged_resolutions
Revises: 0022_conversation_links
Create Date: 2026-08-08 00:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_merged_resolutions"
down_revision = "0022_conversation_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merged_resolutions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("object_ref", sa.String(), nullable=False),
        sa.Column("resolution_kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("base_ref", sa.String(), nullable=True),
        sa.Column("left_candidate_ref", sa.String(), nullable=True),
        sa.Column("right_candidate_ref", sa.String(), nullable=True),
        sa.Column("base_value", sa.JSON(), nullable=True),
        sa.Column("left_candidate", sa.JSON(), nullable=True),
        sa.Column("right_candidate", sa.JSON(), nullable=True),
        sa.Column("merged_value", sa.JSON(), nullable=True),
        sa.Column("auto_merged_patch", sa.JSON(), nullable=False),
        sa.Column("conflict_entries", sa.JSON(), nullable=False),
        sa.Column("recommended_resolution", sa.Text(), nullable=False),
        sa.Column("merged_from", sa.JSON(), nullable=False),
        sa.Column("approval_state", sa.String(), nullable=False),
        sa.Column("approval_ref", sa.String(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "project_id",
        "version_id",
        "task_id",
        "object_ref",
        "status",
        "approval_state",
        "approval_ref",
        "created_at",
        "updated_at",
    ):
        op.create_index(
            f"ix_merged_resolutions_{column}",
            "merged_resolutions",
            [column],
        )


def downgrade() -> None:
    for column in reversed(
        (
            "project_id",
            "version_id",
            "task_id",
            "object_ref",
            "status",
            "approval_state",
            "approval_ref",
            "created_at",
            "updated_at",
        )
    ):
        op.drop_index(
            f"ix_merged_resolutions_{column}",
            table_name="merged_resolutions",
        )
    op.drop_table("merged_resolutions")
