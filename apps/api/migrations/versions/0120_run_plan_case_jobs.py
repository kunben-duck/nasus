"""Case cancellation includes pre-binding preparation and durable same-ID delivery."""
from alembic import op
import sqlalchemy as sa

revision = "0120_run_plan_case_jobs"
down_revision = "0119_run_plan_case_preparations"
branch_labels = None
depends_on = None
TABLES = ("quality_run_plan_case_job_cancellations", "quality_run_plan_case_job_cancel_deliveries")


def upgrade():
    op.create_table(TABLES[0], sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "control_id", "actor_id",
            "command_digest", "preparation_digest", "control_digest", "recorded_at", "status")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("control_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_run_plan_case_preparations.project_id", "quality_run_plan_case_preparations.invocation_id"]),
        sa.ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]))
    op.create_table(TABLES[1], sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "cancellation_digest", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], [TABLES[0] + ".project_id", TABLES[0] + ".invocation_id"]))
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original case cancellation history.")
    for table in reversed(TABLES):
        op.drop_table(table)
