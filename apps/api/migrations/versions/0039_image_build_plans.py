"""Immutable source-pinned investigation proposals, not execution grants."""
from alembic import op
import sqlalchemy as sa

revision = "0039_image_build_plans"
down_revision = "0038_image_candidates"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_build_plans", sa.Column("plan_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "manifest_id", "plan_digest", "created_at", "created_by", "state")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "plan_id"), sa.UniqueConstraint("project_id", "plan_digest"),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        sa.CheckConstraint("state = 'draft'"))
    op.create_index("ix_image_build_plans_project_id", "image_build_plans", ["project_id"])
    op.create_table("image_build_plan_invocations",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False), sa.Column("plan_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]))
    for table in ("image_build_plans", "image_build_plan_invocations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    op.drop_table("image_build_plan_invocations")
    op.drop_table("image_build_plans")
