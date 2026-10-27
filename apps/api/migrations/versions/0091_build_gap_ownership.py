"""Append confirmed gap responsibilities without modifying original reports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0091_build_gap_ownership"
down_revision = "0090_structure_build_lineage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_build_gap_ownership_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("completion_invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False),
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("parent_revision_id", sa.String(), nullable=True),
        sa.Column("parent_revision_hash", sa.String(), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_hash", sa.String(), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("confirmed_by", sa.String(), sa.ForeignKey("user_identities.user_id"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "completion_invocation_id", "revision_id", "revision_hash"),
        sa.UniqueConstraint("completion_invocation_id", "revision_number"),
        sa.ForeignKeyConstraint(["project_id", "completion_invocation_id", "parent_revision_id", "parent_revision_hash"],
            ["image_build_gap_ownership_revisions.project_id", "image_build_gap_ownership_revisions.completion_invocation_id",
             "image_build_gap_ownership_revisions.revision_id", "image_build_gap_ownership_revisions.revision_hash"]),
        sa.CheckConstraint("revision_number BETWEEN 1 AND 80"),
        sa.CheckConstraint("(revision_number = 1 AND parent_revision_id IS NULL AND parent_revision_hash IS NULL) OR (revision_number > 1 AND parent_revision_id IS NOT NULL AND parent_revision_hash IS NOT NULL)"))
    for column in ("project_id", "completion_invocation_id"):
        op.create_index("ix_image_build_gap_ownership_revisions_" + column, "image_build_gap_ownership_revisions", [column])
    op.execute("CREATE TRIGGER immutable_image_build_gap_ownership_revisions BEFORE UPDATE OR DELETE ON image_build_gap_ownership_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_build_gap_ownership_revisions)")):
        raise RuntimeError("Cannot discard confirmed gap responsibility history.")
    op.drop_table("image_build_gap_ownership_revisions")
