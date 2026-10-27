"""Independent original health history; preserve all existing inventory facts."""
from alembic import op
import sqlalchemy as sa

revision = "0106_environment_health"
down_revision = "0105_environment_observations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_run_plan_health_records",
        sa.Column("record_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "run_plan_id", "run_plan_artifact_hash", "build_binding_id", "build_binding_artifact_hash",
            "plan_digest", "image_revision_id", "manifest_id", "environment_id", "operator_policy_digest", "target_artifact_hash",
            "inventory_hash", "health_hash", "observed_at", "invocation_id", "actor_id", "recorded_at", "artifact_ref", "artifact_hash", "request_hash", "status")),
        sa.Column("dependency_health_verified", sa.Boolean(), nullable=False),
        sa.Column("target_health_verified", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "record_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        sa.ForeignKeyConstraint(["project_id", "build_binding_id", "build_binding_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plan_build_bindings.project_id", "quality_run_plan_build_bindings.binding_id", "quality_run_plan_build_bindings.artifact_hash",
             "quality_run_plan_build_bindings.plan_digest", "quality_run_plan_build_bindings.image_revision_id", "quality_run_plan_build_bindings.manifest_id"]),
        sa.CheckConstraint("status = 'recorded'"))
    op.create_index("ix_run_plan_health_history", "quality_run_plan_health_records", ["project_id", "run_plan_id", "record_id"])
    op.execute("CREATE TRIGGER immutable_quality_run_plan_health_records BEFORE UPDATE OR DELETE "
        "ON quality_run_plan_health_records FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_run_plan_health_records)")):
        raise RuntimeError("Cannot discard populated original health history.")
    op.drop_table("quality_run_plan_health_records")
