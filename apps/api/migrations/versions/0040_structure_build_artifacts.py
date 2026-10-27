"""Bind confirmed fixed-input structural work to its immutable candidate."""
from alembic import op
import sqlalchemy as sa

revision = "0040_structure_build_artifacts"
down_revision = "0039_image_build_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_structure_build_artifacts",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "plan_id", "plan_digest", "target_baseline_id", "image_revision_id", "executor_version", "confirmed_at")),
        sa.Column("target_version_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]))
    op.create_index("ix_image_structure_build_artifacts_project_id", "image_structure_build_artifacts", ["project_id"])
    op.execute("CREATE TRIGGER immutable_image_structure_build_artifacts BEFORE UPDATE OR DELETE ON image_structure_build_artifacts FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    op.drop_table("image_structure_build_artifacts")
