"""Append-only original-goal plan phases; each plan requires its own consent."""
from alembic import op
import sqlalchemy as sa

revision = "0087_image_plan_phases"
down_revision = "0086_build_plan_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_image_plan_phases",
        sa.Column("phase_id", sa.String(), primary_key=True), sa.Column("project_id", sa.String(), nullable=False, index=True),
        sa.Column("goal_id", sa.String(), sa.ForeignKey("agent_goals.id"), nullable=False, index=True),
        sa.Column("revision_id", sa.String(), nullable=False), sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("parent_phase_id", sa.String(), nullable=True), sa.Column("phase_number", sa.Integer(), nullable=False),
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("phase_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "phase_id"), sa.UniqueConstraint("goal_id", "phase_number"),
        sa.UniqueConstraint("goal_id", "revision_id"), sa.UniqueConstraint("parent_phase_id"),
        sa.CheckConstraint("phase_number BETWEEN 1 AND 80"),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        sa.ForeignKeyConstraint(["project_id", "revision_id"], ["image_build_plan_revisions.project_id", "image_build_plan_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "parent_phase_id"], ["agent_image_plan_phases.project_id", "agent_image_plan_phases.phase_id"]))
    op.execute("CREATE TRIGGER immutable_agent_image_plan_phases BEFORE UPDATE OR DELETE ON agent_image_plan_phases FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.drop_constraint("image_build_authorizations_goal_id_key", "image_build_authorizations", type_="unique")
    op.create_unique_constraint("uq_build_authorization_goal_plan", "image_build_authorizations", ["goal_id", "plan_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM agent_image_plan_phases)")):
        raise RuntimeError("Cannot discard populated original-goal plan phases.")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_build_authorizations GROUP BY goal_id HAVING count(*) > 1)")):
        raise RuntimeError("Cannot discard independent plan execution consents.")
    op.drop_constraint("uq_build_authorization_goal_plan", "image_build_authorizations", type_="unique")
    op.create_unique_constraint("image_build_authorizations_goal_id_key", "image_build_authorizations", ["goal_id"])
    op.drop_table("agent_image_plan_phases")
