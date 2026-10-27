"""Immutable durable start identities; no invented receipts for legacy goals."""
from alembic import op
import sqlalchemy as sa

revision = "0088_agent_goal_start_receipts"
down_revision = "0087_image_plan_phases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_agent_goal_start_owner", "agent_goals", ["id", "conversation_id", "workflow_id"])
    op.create_table("agent_goal_start_receipts",
        sa.Column("workflow_id", sa.String(), primary_key=True),
        sa.Column("goal_id", sa.String(), nullable=False, unique=True),
        sa.Column("conversation_id", sa.String(), nullable=False, index=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("receipt_hash", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["goal_id", "conversation_id", "workflow_id"],
            ["agent_goals.id", "agent_goals.conversation_id", "agent_goals.workflow_id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation_sessions.id"]),
        sa.CheckConstraint("schema_version = 'nasus.agent-goal-start.v1'"))
    op.execute("CREATE TRIGGER immutable_agent_goal_start_receipts BEFORE UPDATE OR DELETE ON agent_goal_start_receipts FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM agent_goal_start_receipts)")):
        raise RuntimeError("Cannot discard populated durable goal start receipts.")
    op.drop_table("agent_goal_start_receipts")
    op.drop_constraint("uq_agent_goal_start_owner", "agent_goals", type_="unique")
