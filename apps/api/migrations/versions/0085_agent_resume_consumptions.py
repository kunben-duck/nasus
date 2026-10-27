"""Atomic structural continuation receipts; no synthesized legacy consumption."""
from alembic import op
import sqlalchemy as sa

revision = "0085_agent_resume_consumptions"
down_revision = "0084_investigation_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_resume_consumptions",
        sa.Column("goal_id", sa.String(), sa.ForeignKey("agent_goals.id"), primary_key=True),
        sa.Column("checkpoint_digest", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("workflow_id", sa.String(), nullable=True),
        sa.Column("transition_digest", sa.String(), nullable=False),
        sa.Column("receipt_hash", sa.String(), nullable=False))
    op.execute("CREATE TRIGGER immutable_agent_resume_consumptions BEFORE UPDATE OR DELETE ON agent_resume_consumptions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM agent_resume_consumptions)")):
        raise RuntimeError("Cannot discard populated resume history.")
    op.drop_table("agent_resume_consumptions")
