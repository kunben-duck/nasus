"""Fixed reviewed execution inputs; no invented historical target authority."""
from alembic import op
import sqlalchemy as sa

revision = "0101_run_plans"
down_revision = "0100_automation_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_run_plans",
        sa.Column("run_plan_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "context_id", "image_revision_id", "manifest_id", "script_revision_id", "review_revision_id",
            "script_node_key", "script_node_hash", "review_node_key", "review_node_hash", "invocation_id", "artifact_ref",
            "artifact_hash", "request_hash", "plan_digest", "status", "actor_id", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "run_plan_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        sa.ForeignKeyConstraint(["project_id", "script_revision_id", "review_revision_id"],
            ["quality_automation_script_reviews.project_id", "quality_automation_script_reviews.script_revision_id",
             "quality_automation_script_reviews.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "context_id", "script_node_key", "script_node_hash"],
            ["quality_automation_provenance.project_id", "quality_automation_provenance.context_id",
             "quality_automation_provenance.node_key", "quality_automation_provenance.content_hash"]),
        sa.ForeignKeyConstraint(["project_id", "context_id", "review_node_key", "review_node_hash"],
            ["quality_automation_provenance.project_id", "quality_automation_provenance.context_id",
             "quality_automation_provenance.node_key", "quality_automation_provenance.content_hash"]),
        sa.CheckConstraint("status = 'prepared'"),
        sa.CheckConstraint("script_node_key = 'script:' || script_revision_id AND review_node_key = 'script_review:' || review_revision_id"))
    op.create_index("ix_run_plan_script", "quality_run_plans", ["project_id", "script_revision_id", "run_plan_id"])
    op.execute("CREATE TRIGGER immutable_quality_run_plans BEFORE UPDATE OR DELETE ON quality_run_plans "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_run_plans)")):
        raise RuntimeError("Cannot discard populated RunPlan history.")
    op.drop_table("quality_run_plans")
