"""Append-only source-enrichment proposals bound to the original AgentGoal."""
from alembic import op
import sqlalchemy as sa

revision = "0086_build_plan_revisions"
down_revision = "0085_agent_resume_consumptions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_build_plan_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False, index=True),
        sa.Column("goal_id", sa.String(), sa.ForeignKey("agent_goals.id"), nullable=False, index=True),
        sa.Column("root_plan_id", sa.String(), nullable=False),
        sa.Column("from_plan_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("parent_revision_id", sa.String(), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("revision_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "revision_id"), sa.UniqueConstraint("goal_id", "revision_number"),
        sa.UniqueConstraint("parent_revision_id"), sa.CheckConstraint("revision_number BETWEEN 1 AND 80"),
        sa.ForeignKeyConstraint(["project_id", "root_plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        sa.ForeignKeyConstraint(["project_id", "from_plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        sa.ForeignKeyConstraint(["project_id", "parent_revision_id"], ["image_build_plan_revisions.project_id", "image_build_plan_revisions.revision_id"]))
    op.execute("CREATE TRIGGER immutable_image_build_plan_revisions BEFORE UPDATE OR DELETE ON image_build_plan_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_build_plan_revisions)")):
        raise RuntimeError("Cannot discard populated build-plan revision history.")
    op.drop_table("image_build_plan_revisions")
