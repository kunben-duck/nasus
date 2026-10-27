"""Atomic provenance for independently authorized archived-batch recovery."""
from alembic import op
import sqlalchemy as sa

revision = "0065_generation_batch_recovery"
down_revision = "0064_generation_batch_results"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_batch_recovery_results",
        sa.Column("generation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "source_invocation_id", "authority_invocation_id", "artifact_hash", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("authority_invocation_id"),
        sa.CheckConstraint("source_invocation_id <> authority_invocation_id", name="ck_batch_recovery_distinct_authority"),
        sa.ForeignKeyConstraint(["project_id", "generation_id"],
            ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        sa.ForeignKeyConstraint(["generation_id", "source_invocation_id"],
            ["quality_test_design_results.generation_id", "quality_test_design_results.invocation_id"]),
        sa.ForeignKeyConstraint(["authority_invocation_id"], ["tool_invocations.id"]))
    op.execute("CREATE TRIGGER immutable_quality_test_design_batch_recovery_results BEFORE UPDATE OR DELETE ON quality_test_design_batch_recovery_results FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_batch_recovery_results")):
        raise RuntimeError("cannot downgrade while archived batch recovery results exist")
    op.drop_table("quality_test_design_batch_recovery_results")
