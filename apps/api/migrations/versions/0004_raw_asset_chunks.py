"""add raw asset chunks

Revision ID: 0004_raw_asset_chunks
Revises: 0003_run_lifecycle
Create Date: 2026-06-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_raw_asset_chunks"
down_revision = "0003_run_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_asset_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("raw_asset_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("chunk_kind", sa.String(), nullable=False),
        sa.Column("section_path", sa.String(), nullable=False),
        sa.Column("content_ref", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("embedding_record_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_raw_asset_chunks_project_id", "raw_asset_chunks", ["project_id"])
    op.create_index("ix_raw_asset_chunks_raw_asset_id", "raw_asset_chunks", ["raw_asset_id"])
    op.create_index("ix_raw_asset_chunks_source_type", "raw_asset_chunks", ["source_type"])
    op.create_index("ix_raw_asset_chunks_chunk_kind", "raw_asset_chunks", ["chunk_kind"])
    op.create_index("ix_raw_asset_chunks_section_path", "raw_asset_chunks", ["section_path"])
    op.create_index("ix_raw_asset_chunks_content_hash", "raw_asset_chunks", ["content_hash"])
    op.create_index("ix_raw_asset_chunks_embedding_record_id", "raw_asset_chunks", ["embedding_record_id"])
    op.create_index("ix_raw_asset_chunks_created_at", "raw_asset_chunks", ["created_at"])

    op.add_column("embedding_records", sa.Column("chunk_ref", sa.String(), nullable=True))
    op.create_index("ix_embedding_records_chunk_ref", "embedding_records", ["chunk_ref"])


def downgrade() -> None:
    op.drop_index("ix_embedding_records_chunk_ref", table_name="embedding_records")
    op.drop_column("embedding_records", "chunk_ref")
    op.drop_index("ix_raw_asset_chunks_created_at", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_embedding_record_id", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_content_hash", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_section_path", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_chunk_kind", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_source_type", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_raw_asset_id", table_name="raw_asset_chunks")
    op.drop_index("ix_raw_asset_chunks_project_id", table_name="raw_asset_chunks")
    op.drop_table("raw_asset_chunks")
