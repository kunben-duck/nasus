"""Durable AC query egress reservations, completed batches and atomic trace mappings."""
from alembic import op
import sqlalchemy as sa

revision = "0055_context_retrieval_batches"
down_revision = "0054_frozen_retrieval_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("context_retrieval_plans",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "generation_id", "actor_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("project_id", "invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_generations.project_id", "image_index_generations.generation_id"]))
    op.create_table("context_retrieval_calls",
        sa.Column("invocation_id", sa.String(), primary_key=True), sa.Column("ordinal", sa.Integer(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "input_digest", "owner")],
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("ordinal BETWEEN 0 AND 7"),
        sa.UniqueConstraint("project_id", "invocation_id", "ordinal"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["context_retrieval_plans.project_id", "context_retrieval_plans.invocation_id"]))
    op.create_table("context_retrieval_batches",
        sa.Column("invocation_id", sa.String(), primary_key=True), sa.Column("ordinal", sa.Integer(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "artifact_ref", "artifact_hash")],
        sa.ForeignKeyConstraint(["project_id", "invocation_id", "ordinal"],
            ["context_retrieval_calls.project_id", "context_retrieval_calls.invocation_id", "context_retrieval_calls.ordinal"]))
    op.create_table("context_retrieval_results",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "artifact_ref", "artifact_hash", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["context_retrieval_plans.project_id", "context_retrieval_plans.invocation_id"]))
    for table in ("context_retrieval_plans", "context_retrieval_calls", "context_retrieval_batches", "context_retrieval_results"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM context_retrieval_plans")):
        raise RuntimeError("cannot downgrade while context retrieval reservations exist")
    for table in ("context_retrieval_results", "context_retrieval_batches", "context_retrieval_calls", "context_retrieval_plans"):
        op.drop_table(table)
