"""Original case command claim and work binding; no historical consent backfill."""
from alembic import op
import sqlalchemy as sa

revision = "0119_run_plan_case_preparations"
down_revision = "0118_run_plan_case_work"
branch_labels = None
depends_on = None
TABLES = ("quality_run_plan_case_preparations", "quality_run_plan_case_preparation_bindings")


def upgrade():
    op.create_table(TABLES[0], sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in
            ("project_id", "run_id", "selection_digest", "command_digest", "actor_id", "confirmed_at", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("project_id", "run_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    op.create_table(TABLES[1], sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in
            ("project_id", "run_id", "work_id", "preparation_digest", "work_digest", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("work_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            [TABLES[0] + ".project_id", TABLES[0] + ".invocation_id"]),
        sa.ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_run_plan_case_work.project_id", "quality_run_plan_case_work.work_id"]))
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original case preparation history.")
    for table in reversed(TABLES):
        op.drop_table(table)
