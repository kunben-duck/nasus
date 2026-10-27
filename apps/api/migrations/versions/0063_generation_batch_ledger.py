"""Append-only complete batch budgets, per-call claims and native reply receipts."""
from alembic import op
import sqlalchemy as sa

revision = "0063_generation_batch_ledger"
down_revision = "0062_generation_work_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_batch_reservations",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "scope_revision_id", "plan_digest", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("project_id", "invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["scope_revision_id"], ["quality_test_design_scope_revisions.revision_id"]))
    op.create_table("quality_test_design_batch_calls",
        sa.Column("invocation_id", sa.String(), primary_key=True), sa.Column("sequence", sa.Integer(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "batch_digest", "call_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("call_id"),
        sa.UniqueConstraint("invocation_id", "sequence", "call_id"), sa.UniqueConstraint("invocation_id", "batch_digest"),
        sa.CheckConstraint("sequence >= 0 AND sequence < 64", name="ck_generation_batch_call_sequence"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_test_design_batch_reservations.project_id", "quality_test_design_batch_reservations.invocation_id"]))
    op.create_table("quality_test_design_batch_replies",
        sa.Column("invocation_id", sa.String(), primary_key=True), sa.Column("sequence", sa.Integer(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "batch_digest", "call_id", "artifact_ref", "artifact_hash", "response_hash", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("call_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_test_design_batch_reservations.project_id", "quality_test_design_batch_reservations.invocation_id"]),
        sa.ForeignKeyConstraint(["invocation_id", "sequence", "call_id"],
            ["quality_test_design_batch_calls.invocation_id", "quality_test_design_batch_calls.sequence", "quality_test_design_batch_calls.call_id"]),
        sa.ForeignKeyConstraint(["call_id"], ["llm_calls.id"]))
    for table in ("quality_test_design_batch_reservations", "quality_test_design_batch_calls", "quality_test_design_batch_replies"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_batch_reservations")):
        raise RuntimeError("cannot downgrade while generation batch reservations exist")
    op.drop_table("quality_test_design_batch_replies")
    op.drop_table("quality_test_design_batch_calls")
    op.drop_table("quality_test_design_batch_reservations")
