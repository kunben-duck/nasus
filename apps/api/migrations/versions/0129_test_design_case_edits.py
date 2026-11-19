"""Preserve model drafts and append independently reviewable human case revisions."""
from alembic import op
import sqlalchemy as sa

revision = "0129_test_design_case_edits"
down_revision = "0128_iteration_image_adoptions"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_test_design_result_call_kind", "quality_test_design_results", type_="check")
    op.create_check_constraint("ck_test_design_result_call_kind", "quality_test_design_results",
        "(provenance_kind = 'single' AND call_id IS NOT NULL) OR (provenance_kind IN ('batch', 'human_revision') AND call_id IS NULL)")
    op.create_table("quality_test_design_case_edits",
        sa.Column("generation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "parent_generation_id", "invocation_id", "actor_id", "request_hash", "artifact_hash")],
        sa.UniqueConstraint("parent_generation_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        sa.ForeignKeyConstraint(["project_id", "parent_generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    op.execute("CREATE TRIGGER immutable_quality_test_design_case_edits BEFORE UPDATE OR DELETE ON quality_test_design_case_edits "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_results WHERE provenance_kind = 'human_revision'")):
        raise RuntimeError("cannot discard human case revision history")
    op.drop_table("quality_test_design_case_edits")
    op.drop_constraint("ck_test_design_result_call_kind", "quality_test_design_results", type_="check")
    op.create_check_constraint("ck_test_design_result_call_kind", "quality_test_design_results",
        "(provenance_kind = 'single' AND call_id IS NOT NULL) OR (provenance_kind = 'batch' AND call_id IS NULL)")
