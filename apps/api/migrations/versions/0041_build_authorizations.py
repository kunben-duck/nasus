"""Persist fixed-plan consent and consume each approved work item once."""
from alembic import op
import sqlalchemy as sa

revision = "0041_build_authorizations"
down_revision = "0040_structure_build_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_build_authorizations",
        sa.Column("authorization_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), sa.ForeignKey("agent_goals.id"), nullable=False, unique=True),
        sa.Column("authorization_invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]))
    op.create_index("ix_image_build_authorizations_project_id", "image_build_authorizations", ["project_id"])
    op.create_table("image_build_work_reservations",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("authorization_id", sa.String(), sa.ForeignKey("image_build_authorizations.authorization_id"), nullable=False),
        sa.Column("work_item_id", sa.String(), nullable=False),
        sa.UniqueConstraint("authorization_id", "work_item_id"))
    for table in ("image_build_authorizations", "image_build_work_reservations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    op.drop_table("image_build_work_reservations")
    op.drop_table("image_build_authorizations")
