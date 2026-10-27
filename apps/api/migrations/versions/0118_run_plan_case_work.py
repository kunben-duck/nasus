"""Fixed case dispatch ledger; no backfill of historical runs or execution consent."""
from alembic import op
import sqlalchemy as sa

revision = "0118_run_plan_case_work"
down_revision = "0117_fixture_preparation_cancel"
branch_labels = None
depends_on = None

TABLES = ("quality_run_plan_case_work", "quality_run_plan_case_leases", "quality_run_plan_case_claims",
          "quality_run_plan_case_outcomes", "quality_run_plan_case_cancellations")


def strings(names):
    return [sa.Column(name, sa.String(), nullable=False) for name in names]


def payload():
    return [sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False)]


def upgrade():
    op.create_table(TABLES[0], sa.Column("work_id", sa.String(), primary_key=True),
        *strings(("project_id", "run_id", "invocation_id", "actor_id", "run_plan_id", "run_plan_artifact_hash",
            "plan_digest", "image_revision_id", "manifest_id", "scope_digest", "roster_digest", "recorded_at", "content_hash")),
        sa.Column("scope", sa.JSON(), nullable=False), sa.Column("roster", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "work_id"), sa.UniqueConstraint("project_id", "run_id"),
        sa.UniqueConstraint("invocation_id"), sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]))
    op.create_table(TABLES[1], sa.Column("work_id", sa.String(), primary_key=True), *strings(("project_id", "owner_id")),
        sa.Column("epoch", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.DateTime(timezone=True), nullable=False) for name in ("acquired_at", "renewed_at", "expires_at")),
        sa.ForeignKeyConstraint(["project_id", "work_id"], [TABLES[0] + ".project_id", TABLES[0] + ".work_id"]),
        sa.CheckConstraint("epoch >= 1 AND acquired_at <= renewed_at AND renewed_at < expires_at"),
        sa.CheckConstraint("expires_at = renewed_at + INTERVAL '90 seconds'"))
    op.create_table(TABLES[2], sa.Column("claim_id", sa.String(), primary_key=True),
        *strings(("project_id", "work_id", "case_id", "owner_id", "recorded_at")),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("epoch", sa.Integer(), nullable=False), *payload(),
        sa.UniqueConstraint("project_id", "claim_id"), sa.UniqueConstraint("work_id", "case_id"), sa.UniqueConstraint("work_id", "ordinal"),
        sa.ForeignKeyConstraint(["project_id", "work_id"], [TABLES[0] + ".project_id", TABLES[0] + ".work_id"]),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 512 AND epoch >= 1"))
    op.create_table(TABLES[3], sa.Column("claim_id", sa.String(), primary_key=True),
        *strings(("project_id", "status", "recorded_at", "artifact_ref", "artifact_hash", "observation_digest")), *payload(),
        sa.ForeignKeyConstraint(["project_id", "claim_id"], [TABLES[2] + ".project_id", TABLES[2] + ".claim_id"]),
        sa.CheckConstraint("status IN ('passed', 'failed', 'error', 'timed_out')"))
    op.create_table(TABLES[4], sa.Column("work_id", sa.String(), primary_key=True),
        *strings(("project_id", "control_id", "actor_id", "recorded_at")), *payload(), sa.UniqueConstraint("control_id"),
        sa.ForeignKeyConstraint(["project_id", "work_id"], [TABLES[0] + ".project_id", TABLES[0] + ".work_id"]),
        sa.ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]))
    for table in (TABLES[0], TABLES[2], TABLES[3], TABLES[4]):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.execute("""CREATE FUNCTION nasus_guard_run_plan_case_lease() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Cannot discard original case ownership'; END IF;
            IF NEW.work_id IS DISTINCT FROM OLD.work_id OR NEW.project_id IS DISTINCT FROM OLD.project_id
                OR NEW.epoch < OLD.epoch OR NEW.epoch > OLD.epoch + 1
                OR NEW.acquired_at > clock_timestamp() OR NEW.renewed_at > clock_timestamp() THEN
                RAISE EXCEPTION 'Cannot rebind or regress original case ownership';
            END IF;
            IF NEW.epoch = OLD.epoch THEN
                IF NEW.owner_id IS DISTINCT FROM OLD.owner_id OR NEW.acquired_at IS DISTINCT FROM OLD.acquired_at
                    OR NEW.renewed_at < OLD.renewed_at OR NEW.expires_at < OLD.expires_at
                    OR OLD.expires_at <= clock_timestamp() THEN
                    RAISE EXCEPTION 'Cannot revive or change an original case lease';
                END IF;
            ELSIF OLD.expires_at > clock_timestamp() THEN
                RAISE EXCEPTION 'Cannot steal a live original case lease';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(f"CREATE TRIGGER guarded_{TABLES[1]} BEFORE UPDATE OR DELETE ON {TABLES[1]} "
        "FOR EACH ROW EXECUTE FUNCTION nasus_guard_run_plan_case_lease()")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original RunPlan case history.")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_guard_run_plan_case_lease()")
