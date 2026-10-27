"""Append original observations, never infer historical execution authority."""
from alembic import op
import sqlalchemy as sa

revision = "0104_run_plan_observations"
down_revision = "0103_run_plan_build_bindings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_run_plan_observation_records",
        sa.Column("record_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id",
            "invocation_id", "actor_id", "recorded_at", "artifact_ref", "artifact_hash", "collection_digest", "request_hash", "run_id", "status")),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in ("case_count", "observed_case_count",
            "outcome_unknown_case_count", "no_result_case_count", "passed_observation_count", "failed_observation_count")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "record_id"), sa.UniqueConstraint("invocation_id"),
        sa.UniqueConstraint("project_id", "run_plan_id", "run_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        sa.CheckConstraint("status = 'recorded'"),
        sa.CheckConstraint("case_count BETWEEN 1 AND 512 AND observed_case_count >= 0 AND outcome_unknown_case_count >= 0 "
            "AND no_result_case_count >= 0 AND case_count = observed_case_count + outcome_unknown_case_count + no_result_case_count "
            "AND passed_observation_count >= 0 AND failed_observation_count >= 0 "
            "AND passed_observation_count + failed_observation_count <= observed_case_count"))
    op.create_table("quality_run_plan_case_observations",
        sa.Column("record_id", sa.String(), primary_key=True), sa.Column("case_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "case_digest", "status", "content_hash")),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("observation_digest", sa.String(), nullable=True),
        sa.Column("attempt_digest", sa.String(), nullable=True), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("record_id", "ordinal"),
        sa.ForeignKeyConstraint(["project_id", "record_id"],
            ["quality_run_plan_observation_records.project_id", "quality_run_plan_observation_records.record_id"]),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 511"),
        sa.CheckConstraint("status IN ('passed', 'failed', 'error', 'timed_out', 'not_executed', 'not_observed', 'outcome_unknown')"),
        sa.CheckConstraint("(status = 'outcome_unknown' AND observation_digest IS NULL AND attempt_digest IS NOT NULL) "
            "OR (status IN ('not_executed', 'not_observed') AND observation_digest IS NULL AND attempt_digest IS NULL) "
            "OR (status IN ('passed', 'failed', 'error', 'timed_out') AND observation_digest IS NOT NULL AND attempt_digest IS NULL)"))
    for table in ("quality_run_plan_observation_records", "quality_run_plan_case_observations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_run_plan_case_observations", "quality_run_plan_observation_records"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated RunPlan observation history.")
    op.drop_table("quality_run_plan_case_observations")
    op.drop_table("quality_run_plan_observation_records")
