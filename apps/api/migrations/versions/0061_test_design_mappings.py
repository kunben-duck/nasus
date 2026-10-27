"""Independent append-only mapping review; draft archives remain unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0061_test_design_mappings"
down_revision = "0060_generation_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_mapping_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "generation_id", "project_id", "status", "invocation_id", "artifact_ref", "content_hash")],
        sa.Column("previous_revision_id", sa.String(), nullable=True), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("generation_id", "sequence"), sa.UniqueConstraint("project_id", "generation_id", "revision_id"),
        sa.UniqueConstraint("previous_revision_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id", "previous_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id", "quality_test_design_mapping_revisions.revision_id"]),
        sa.CheckConstraint("status IN ('reviewed', 'withdrawn')"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'reviewed') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"))
    op.create_index("ix_quality_test_design_mapping_revisions_generation_id", "quality_test_design_mapping_revisions", ["generation_id"])
    op.create_index("uq_mapping_review_first", "quality_test_design_mapping_revisions", ["generation_id"], unique=True,
        postgresql_where=sa.text("previous_revision_id IS NULL"))
    op.execute("CREATE TRIGGER immutable_quality_test_design_mapping_revisions BEFORE UPDATE OR DELETE ON quality_test_design_mapping_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_mapping_revisions")):
        raise RuntimeError("cannot downgrade while mapping reviews exist")
    op.drop_table("quality_test_design_mapping_revisions")
