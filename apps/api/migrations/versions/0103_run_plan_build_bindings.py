"""Append exact original native-build bindings; never rewrite v1 plan declarations."""
from alembic import op
import sqlalchemy as sa

revision = "0103_run_plan_build_bindings"
down_revision = "0102_native_builds"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_run_plan_build_parent", "quality_run_plans",
        ["project_id", "run_plan_id", "artifact_hash", "plan_digest", "image_revision_id", "manifest_id"])
    op.create_unique_constraint("uq_native_build_binding_source", "quality_native_build_reservations",
        ["project_id", "invocation_id", "build_id", "image_revision_id", "manifest_id", "binding_id", "source_revision_id"])
    op.create_unique_constraint("uq_native_build_binding_parent", "quality_native_build_results",
        ["project_id", "invocation_id", "build_id", "artifact_hash", "receipt_digest"])
    op.create_table("quality_run_plan_build_bindings",
        sa.Column("binding_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id",
            "target_build_invocation_id", "target_artifact_hash", "invocation_id", "artifact_ref", "artifact_hash",
            "binding_digest", "request_hash", "status", "actor_id", "recorded_at")),
        sa.Column("code_source_count", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "image_revision_id", "manifest_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        sa.CheckConstraint("status = 'build_attested' AND code_source_count >= 1 AND code_source_count <= 1000"))
    op.create_index("ix_run_plan_build_history", "quality_run_plan_build_bindings", ["project_id", "run_plan_id", "binding_id"])
    op.create_table("quality_run_plan_build_members",
        sa.Column("binding_id", sa.String(), primary_key=True), sa.Column("native_invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "image_revision_id", "manifest_id", "source_binding_id", "source_revision_id", "build_id", "archive_hash", "receipt_digest")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "native_invocation_id"),
        sa.UniqueConstraint("project_id", "binding_id", "source_binding_id"),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "image_revision_id", "manifest_id"],
            ["quality_run_plan_build_bindings.project_id", "quality_run_plan_build_bindings.binding_id",
             "quality_run_plan_build_bindings.image_revision_id", "quality_run_plan_build_bindings.manifest_id"]),
        sa.ForeignKeyConstraint(["project_id", "native_invocation_id", "build_id", "archive_hash", "receipt_digest"],
            ["quality_native_build_results.project_id", "quality_native_build_results.invocation_id",
             "quality_native_build_results.build_id", "quality_native_build_results.artifact_hash", "quality_native_build_results.receipt_digest"]),
        sa.ForeignKeyConstraint(["project_id", "native_invocation_id", "build_id", "image_revision_id", "manifest_id", "source_binding_id", "source_revision_id"],
            ["quality_native_build_reservations.project_id", "quality_native_build_reservations.invocation_id",
             "quality_native_build_reservations.build_id", "quality_native_build_reservations.image_revision_id",
             "quality_native_build_reservations.manifest_id", "quality_native_build_reservations.binding_id", "quality_native_build_reservations.source_revision_id"]))
    op.create_foreign_key("fk_run_plan_build_target_member", "quality_run_plan_build_bindings", "quality_run_plan_build_members",
        ["project_id", "binding_id", "target_build_invocation_id"], ["project_id", "binding_id", "native_invocation_id"],
        deferrable=True, initially="DEFERRED")
    for table in ("quality_run_plan_build_bindings", "quality_run_plan_build_members"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_run_plan_build_bindings", "quality_run_plan_build_members"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated RunPlan build binding history.")
    op.drop_constraint("fk_run_plan_build_target_member", "quality_run_plan_build_bindings", type_="foreignkey")
    op.drop_table("quality_run_plan_build_members")
    op.drop_table("quality_run_plan_build_bindings")
    op.drop_constraint("uq_native_build_binding_parent", "quality_native_build_results", type_="unique")
    op.drop_constraint("uq_native_build_binding_source", "quality_native_build_reservations", type_="unique")
    op.drop_constraint("uq_run_plan_build_parent", "quality_run_plans", type_="unique")
