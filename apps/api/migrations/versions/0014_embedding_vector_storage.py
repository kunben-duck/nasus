"""persist system-image vectors and searchable projection text

Revision ID: 0014_embedding_vector_storage
Revises: 0013_agent_goal_planning_facts
Create Date: 2026-07-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision = "0014_embedding_vector_storage"
down_revision = "0013_agent_goal_planning_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("embedding_records", sa.Column("embedding_vector", Vector(), nullable=True))
    op.add_column(
        "embedding_records",
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_embedding_records_retrieval_scope",
        "embedding_records",
        ["project_id", "baseline_id", "embedding_model", "dimensions", "status"],
    )
    op.execute(
        "CREATE INDEX ix_embedding_records_search_text_fts "
        "ON embedding_records USING gin (to_tsvector('simple', search_text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embedding_records_search_text_fts")
    op.drop_index("ix_embedding_records_retrieval_scope", table_name="embedding_records")
    op.drop_column("embedding_records", "search_text")
    op.drop_column("embedding_records", "embedding_vector")
