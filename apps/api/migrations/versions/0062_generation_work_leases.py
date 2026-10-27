"""Fenced PostgreSQL worker leases for canonical generation activities."""
from alembic import op
import sqlalchemy as sa

revision = "0062_generation_work_leases"
down_revision = "0061_test_design_mappings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_work_leases",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("epoch >= 1", name="ck_generation_work_lease_epoch"))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_work_leases")):
        raise RuntimeError("cannot downgrade while generation work leases exist")
    op.drop_table("quality_test_design_work_leases")
