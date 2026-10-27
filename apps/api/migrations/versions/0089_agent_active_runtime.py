"""Active runtime accounting is additive; legacy history is not inferred."""
from alembic import op
import sqlalchemy as sa

revision = "0089_agent_active_runtime"
down_revision = "0088_agent_goal_start_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_goals", sa.Column("active_runtime_ms", sa.BigInteger(), nullable=True))
    op.add_column("agent_goals", sa.Column("active_started_at", sa.String(), nullable=True))
    op.create_check_constraint("ck_agent_goal_active_runtime_nonnegative", "agent_goals", "active_runtime_ms IS NULL OR active_runtime_ms >= 0")
    op.create_check_constraint("ck_agent_goal_active_runtime_interval", "agent_goals", "active_started_at IS NULL OR active_runtime_ms IS NOT NULL")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM agent_goals WHERE active_runtime_ms IS NOT NULL OR active_started_at IS NOT NULL)")):
        raise RuntimeError("Cannot discard populated active runtime accounting or v2 goal checkpoints.")
    op.drop_constraint("ck_agent_goal_active_runtime_interval", "agent_goals", type_="check")
    op.drop_constraint("ck_agent_goal_active_runtime_nonnegative", "agent_goals", type_="check")
    op.drop_column("agent_goals", "active_started_at")
    op.drop_column("agent_goals", "active_runtime_ms")
