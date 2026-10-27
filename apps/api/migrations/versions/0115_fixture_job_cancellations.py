"""Original fixture cancellation and delivery facts; no private-history promotion."""
from alembic import op
import sqlalchemy as sa

revision = "0115_fixture_job_cancellations"
down_revision = "0114_fixture_command_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_http_fixture_cancellations", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "control_id", "control_digest",
            "request_digest", "actor_id", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("control_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_commands.project_id", "quality_http_fixture_commands.invocation_id"]),
        sa.ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]))
    op.create_table("quality_http_fixture_cancellation_deliveries", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "cancellation_digest", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_cancellations.project_id", "quality_http_fixture_cancellations.invocation_id"]))
    for table in ("quality_http_fixture_cancellations", "quality_http_fixture_cancellation_deliveries"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_http_fixture_cancellation_deliveries", "quality_http_fixture_cancellations"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original fixture cancellation history.")
    op.drop_table("quality_http_fixture_cancellation_deliveries")
    op.drop_table("quality_http_fixture_cancellations")
