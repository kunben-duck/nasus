"""Append-only unbound cancellation; never backfill or manufacture an intent."""
from alembic import op
import sqlalchemy as sa

revision = "0117_fixture_preparation_cancel"
down_revision = "0116_fixture_preparations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_http_fixture_preparation_cancellations", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "preparation_digest", "control_id",
            "control_digest", "request_digest", "actor_id", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("control_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_preparations.project_id", "quality_http_fixture_preparations.invocation_id"]),
        sa.ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]))
    op.create_table("quality_http_fixture_preparation_cancel_deliveries", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "cancellation_digest", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_preparation_cancellations.project_id", "quality_http_fixture_preparation_cancellations.invocation_id"]))
    for table in ("quality_http_fixture_preparation_cancellations", "quality_http_fixture_preparation_cancel_deliveries"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_http_fixture_preparation_cancel_deliveries", "quality_http_fixture_preparation_cancellations"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original fixture preparation cancellation history.")
    op.drop_table("quality_http_fixture_preparation_cancel_deliveries")
    op.drop_table("quality_http_fixture_preparation_cancellations")
