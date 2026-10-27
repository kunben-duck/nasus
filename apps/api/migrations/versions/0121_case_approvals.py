"""Independent case admission; no automatic promotion of old mapping decisions."""
from alembic import op
import sqlalchemy as sa

revision = "0121_case_approvals"
down_revision = "0120_run_plan_case_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_case_approval_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("generation_id", sa.String(), nullable=False), sa.Column("mapping_revision_id", sa.String(), nullable=False),
        sa.Column("cohort_id", sa.String(), nullable=False), sa.Column("previous_revision_id", sa.String()),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("invocation_id", sa.String(), nullable=False), sa.Column("artifact_ref", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("cohort_id", "sequence"), sa.UniqueConstraint("invocation_id"), sa.UniqueConstraint("previous_revision_id"),
        sa.UniqueConstraint("project_id", "generation_id", "revision_id"), sa.UniqueConstraint("project_id", "cohort_id", "revision_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id", "mapping_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id", "quality_test_design_mapping_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "cohort_id", "previous_revision_id"],
            ["quality_case_approval_revisions.project_id", "quality_case_approval_revisions.cohort_id", "quality_case_approval_revisions.revision_id"]),
        sa.CheckConstraint("status IN ('approved', 'withdrawn')"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'approved') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"))
    op.create_index("ix_quality_case_approval_revisions_cohort_id", "quality_case_approval_revisions", ["cohort_id"])
    op.create_index("uq_case_approval_first", "quality_case_approval_revisions", ["cohort_id"], unique=True,
        postgresql_where=sa.text("previous_revision_id IS NULL"))
    op.create_table("quality_case_approval_members",
        sa.Column("revision_id", sa.String(), primary_key=True), sa.Column("case_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False), sa.Column("generation_id", sa.String(), nullable=False),
        sa.Column("case_digest", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "generation_id", "revision_id"],
            ["quality_case_approval_revisions.project_id", "quality_case_approval_revisions.generation_id", "quality_case_approval_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["generation_id", "case_id"], ["quality_test_design_case_revisions.generation_id", "quality_test_design_case_revisions.case_id"]))
    for table in ("quality_case_approval_revisions", "quality_case_approval_members"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_case_approval_revisions)")):
        raise RuntimeError("Cannot discard populated independent case admission history.")
    op.drop_table("quality_case_approval_members")
    op.drop_table("quality_case_approval_revisions")
