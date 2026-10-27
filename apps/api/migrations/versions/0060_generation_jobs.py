"""Durable cancellation delivery for native generation and response recovery."""
from alembic import op
import sqlalchemy as sa

revision = "0060_generation_jobs"
down_revision = "0059_generation_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_cancellations",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_cancellations")):
        raise RuntimeError("cannot downgrade while generation cancellation receipts exist")
    op.drop_table("quality_test_design_cancellations")
