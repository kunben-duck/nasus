"""Durable delivery of cancellation for context retrieval workflows."""
from alembic import op
import sqlalchemy as sa

revision = "0056_context_retrieval_cancel"
down_revision = "0055_context_retrieval_batches"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("context_retrieval_cancellations",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    # Older cancellations may have committed before a failed Temporal RPC.
    op.execute("""INSERT INTO context_retrieval_cancellations
        (invocation_id, project_id, requested_at)
        SELECT id, input_payload->>'project_id', CURRENT_TIMESTAMP FROM tool_invocations
        WHERE tool_id = 'system_image.context.retrieve' AND status = 'cancelled'
          AND input_payload->>'project_id' IS NOT NULL""")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM context_retrieval_cancellations")):
        raise RuntimeError("cannot downgrade while context retrieval cancellation receipts exist")
    op.drop_table("context_retrieval_cancellations")
