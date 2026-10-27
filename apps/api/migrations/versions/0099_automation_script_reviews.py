"""Append independent DSL/oracle reviews; never rewrite original drafts."""
from alembic import op
import sqlalchemy as sa

revision = "0099_automation_script_reviews"
down_revision = "0098_automation_script_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_automation_script_reviews",
        sa.Column("revision_id", sa.String(), primary_key=True), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("script_revision_id", sa.String(), nullable=False), sa.Column("previous_revision_id", sa.String()),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("artifact_ref", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("script_revision_id", "sequence"),
        sa.UniqueConstraint("project_id", "script_revision_id", "revision_id"), sa.UniqueConstraint("previous_revision_id"),
        sa.ForeignKeyConstraint(["project_id", "script_revision_id"],
            ["quality_automation_script_revisions.project_id", "quality_automation_script_revisions.script_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "script_revision_id", "previous_revision_id"],
            ["quality_automation_script_reviews.project_id", "quality_automation_script_reviews.script_revision_id",
             "quality_automation_script_reviews.revision_id"]),
        sa.CheckConstraint("status IN ('reviewed', 'withdrawn')"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'reviewed') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"))
    op.create_index("ix_quality_automation_script_reviews_script_revision_id", "quality_automation_script_reviews", ["script_revision_id"])
    op.create_index("uq_script_review_first", "quality_automation_script_reviews", ["script_revision_id"], unique=True,
        postgresql_where=sa.text("previous_revision_id IS NULL"))
    op.execute("CREATE TRIGGER immutable_quality_automation_script_reviews BEFORE UPDATE OR DELETE ON quality_automation_script_reviews "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_automation_script_reviews)")):
        raise RuntimeError("Cannot discard populated automation script review history.")
    op.drop_table("quality_automation_script_reviews")
