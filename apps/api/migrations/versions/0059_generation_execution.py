"""Durable generation budget reservations and private native reply receipts."""
from alembic import op
import sqlalchemy as sa

revision = "0059_generation_execution"
down_revision = "0058_test_design_results"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_call_reservations",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "scope_revision_id", "call_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("call_id"),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("invocation_id", "call_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["scope_revision_id"], ["quality_test_design_scope_revisions.revision_id"]))
    op.create_table("quality_test_design_native_replies",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "call_id", "artifact_ref", "artifact_hash", "response_hash", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("call_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["quality_test_design_call_reservations.project_id", "quality_test_design_call_reservations.invocation_id"]),
        sa.ForeignKeyConstraint(["invocation_id", "call_id"], ["quality_test_design_call_reservations.invocation_id", "quality_test_design_call_reservations.call_id"]),
        sa.ForeignKeyConstraint(["call_id"], ["llm_calls.id"]))
    for table in ("quality_test_design_call_reservations", "quality_test_design_native_replies"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_call_reservations")):
        raise RuntimeError("cannot downgrade while generation reservations exist")
    op.drop_table("quality_test_design_native_replies")
    op.drop_table("quality_test_design_call_reservations")
