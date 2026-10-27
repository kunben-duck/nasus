"""Versioned multi-call draft results with exact native reply provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0064_generation_batch_results"
down_revision = "0063_generation_batch_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("quality_test_design_results", sa.Column("provenance_kind", sa.String(), nullable=False, server_default="single"))
    op.alter_column("quality_test_design_results", "call_id", existing_type=sa.String(), nullable=True)
    op.create_check_constraint("ck_test_design_result_call_kind", "quality_test_design_results",
        "(provenance_kind = 'single' AND call_id IS NOT NULL) OR (provenance_kind = 'batch' AND call_id IS NULL)")
    op.create_unique_constraint("uq_test_design_result_invocation_pin", "quality_test_design_results", ["generation_id", "invocation_id"])
    op.create_unique_constraint("uq_generation_batch_reply_call_pin", "quality_test_design_batch_replies", ["invocation_id", "sequence", "call_id"])
    op.create_table("quality_test_design_result_batch_calls",
        sa.Column("generation_id", sa.String(), primary_key=True), sa.Column("sequence", sa.Integer(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "invocation_id", "call_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("generation_id", "call_id"),
        sa.CheckConstraint("sequence >= 0 AND sequence < 64", name="ck_test_design_result_batch_sequence"),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        sa.ForeignKeyConstraint(["generation_id", "invocation_id"], ["quality_test_design_results.generation_id", "quality_test_design_results.invocation_id"]),
        sa.ForeignKeyConstraint(["invocation_id", "sequence", "call_id"], ["quality_test_design_batch_replies.invocation_id", "quality_test_design_batch_replies.sequence", "quality_test_design_batch_replies.call_id"]))
    op.execute("CREATE TRIGGER immutable_quality_test_design_result_batch_calls BEFORE UPDATE OR DELETE ON quality_test_design_result_batch_calls FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_results WHERE provenance_kind = 'batch'")):
        raise RuntimeError("cannot downgrade while multi-call test-design results exist")
    op.drop_table("quality_test_design_result_batch_calls")
    op.drop_constraint("uq_generation_batch_reply_call_pin", "quality_test_design_batch_replies", type_="unique")
    op.drop_constraint("uq_test_design_result_invocation_pin", "quality_test_design_results", type_="unique")
    op.drop_constraint("ck_test_design_result_call_kind", "quality_test_design_results", type_="check")
    op.alter_column("quality_test_design_results", "call_id", existing_type=sa.String(), nullable=False)
    op.drop_column("quality_test_design_results", "provenance_kind")
