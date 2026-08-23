"""add explainable release readiness evidence

Revision ID: 0018_release_readiness_evidence
Revises: 0017_langgraph_checkpoints
Create Date: 2026-07-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_release_readiness_evidence"
down_revision = "0017_langgraph_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "release_readiness",
        sa.Column("score_breakdown", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "release_readiness",
        sa.Column("evidence_summary", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("release_readiness", "evidence_summary")
    op.drop_column("release_readiness", "score_breakdown")
