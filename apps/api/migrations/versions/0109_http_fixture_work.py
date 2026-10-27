"""Durable private worker fencing; no legacy history receives execution consent."""
from alembic import op
import sqlalchemy as sa

revision = "0109_http_fixture_work"
down_revision = "0108_http_fixture_journals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_http_fixture_work_leases",
        sa.Column("work_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "attempt_id", "case_id", "operation", "run_plan_id", "run_plan_artifact_hash", "plan_digest",
            "image_revision_id", "manifest_id", "scope_digest", "request_digest", "actor_id", "owner_id")),
        sa.Column("scope", sa.JSON(), nullable=False), sa.Column("epoch", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.DateTime(timezone=True), nullable=False) for name in ("acquired_at", "renewed_at", "expires_at")),
        sa.UniqueConstraint("project_id", "work_id"), sa.UniqueConstraint("project_id", "attempt_id", "case_id", "operation"),
        sa.ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        sa.CheckConstraint("operation IN ('setup', 'cleanup') AND epoch >= 1"),
        sa.CheckConstraint("acquired_at <= renewed_at AND renewed_at < expires_at"))
    op.execute("""
        CREATE FUNCTION nasus_guard_http_fixture_work() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Original fixture work history cannot be deleted';
            END IF;
            IF ROW(NEW.work_id, NEW.project_id, NEW.attempt_id, NEW.case_id, NEW.operation,
                    NEW.run_plan_id, NEW.run_plan_artifact_hash, NEW.plan_digest, NEW.image_revision_id,
                    NEW.manifest_id, NEW.scope_digest, NEW.request_digest, NEW.actor_id)
                IS DISTINCT FROM ROW(OLD.work_id, OLD.project_id, OLD.attempt_id, OLD.case_id, OLD.operation,
                    OLD.run_plan_id, OLD.run_plan_artifact_hash, OLD.plan_digest, OLD.image_revision_id,
                    OLD.manifest_id, OLD.scope_digest, OLD.request_digest, OLD.actor_id)
                OR NEW.scope::jsonb IS DISTINCT FROM OLD.scope::jsonb
                OR NEW.renewed_at < OLD.renewed_at
                OR (NEW.epoch = OLD.epoch AND (NEW.owner_id <> OLD.owner_id OR NEW.acquired_at <> OLD.acquired_at))
                OR (NEW.epoch <> OLD.epoch AND (NEW.epoch <> OLD.epoch + 1 OR OLD.expires_at > clock_timestamp()))
            THEN
                RAISE EXCEPTION 'Original fixture work pins and live ownership cannot be rebound';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("CREATE TRIGGER guarded_quality_http_fixture_work_leases BEFORE UPDATE OR DELETE "
        "ON quality_http_fixture_work_leases FOR EACH ROW EXECUTE FUNCTION nasus_guard_http_fixture_work()")
    op.create_table("quality_http_fixture_dispatch_ownership",
        sa.Column("claim_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "work_id", "owner_id", "request_digest", "dispatch_digest", "recorded_at")),
        sa.Column("epoch", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        sa.ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_http_fixture_work_leases.project_id", "quality_http_fixture_work_leases.work_id"]),
        sa.CheckConstraint("epoch >= 1"))
    op.execute("CREATE TRIGGER immutable_quality_http_fixture_dispatch_ownership BEFORE UPDATE OR DELETE "
        "ON quality_http_fixture_dispatch_ownership FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_http_fixture_dispatch_ownership", "quality_http_fixture_work_leases"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original fixture work history.")
    op.drop_table("quality_http_fixture_dispatch_ownership")
    op.drop_table("quality_http_fixture_work_leases")
    op.execute("DROP FUNCTION nasus_guard_http_fixture_work()")
