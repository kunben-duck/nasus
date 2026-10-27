"""Private immutable fixture claims and original results; no execution authority."""
from alembic import op
import sqlalchemy as sa

revision = "0108_http_fixture_journals"
down_revision = "0107_http_locator_records"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_http_fixture_dispatches",
        sa.Column("claim_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "attempt_id", "case_id", "phase", "run_plan_id", "run_plan_artifact_hash", "plan_digest",
            "image_revision_id", "manifest_id", "scope_digest", "command_digest", "request_hash", "actor_id", "recorded_at", "status")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "claim_id"),
        sa.UniqueConstraint("project_id", "attempt_id", "case_id", "phase"),
        sa.ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        sa.CheckConstraint("status = 'reserved'"), sa.CheckConstraint("phase = 'setup' OR phase LIKE 'cleanup:%'"))
    op.create_table("quality_http_fixture_results",
        sa.Column("claim_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "actor_id", "recorded_at", "status", "dispatch_digest", "receipt_digest", "artifact_ref", "artifact_hash")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        sa.CheckConstraint("status IN ('passed', 'failed', 'error', 'timed_out')"))
    for table in ("quality_http_fixture_dispatches", "quality_http_fixture_results"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_http_fixture_results", "quality_http_fixture_dispatches"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original fixture history.")
    op.drop_table("quality_http_fixture_results")
    op.drop_table("quality_http_fixture_dispatches")
