"""Versioned semantic checkpoints and durable compaction jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0124_conversation_memory"
down_revision = "0123_fixed_git_commit"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversation_summary_checkpoints", sa.Column("memory_payload", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("conversation_memory_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("checkpoint_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False))
    op.create_index("ix_conversation_memory_jobs_conversation_id", "conversation_memory_jobs", ["conversation_id"])
    op.create_index("ix_conversation_memory_jobs_status", "conversation_memory_jobs", ["status"])


def downgrade():
    op.drop_table("conversation_memory_jobs")
    op.drop_column("conversation_summary_checkpoints", "memory_payload")
