"""Durable original preparation, without backfilling or promoting old commands."""
from alembic import op
import sqlalchemy as sa

revision = "0116_fixture_preparations"
down_revision = "0115_fixture_job_cancellations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_http_fixture_preparations", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in
            ("project_id", "request_digest", "actor_id", "confirmed_at", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    op.create_table("quality_http_fixture_preparation_bindings", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in
            ("project_id", "preparation_digest", "intent_digest", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_preparations.project_id", "quality_http_fixture_preparations.invocation_id"]),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_commands.project_id", "quality_http_fixture_commands.invocation_id"]))
    for table in ("quality_http_fixture_preparations", "quality_http_fixture_preparation_bindings"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_http_fixture_preparation_bindings", "quality_http_fixture_preparations"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original fixture preparation history.")
    op.drop_table("quality_http_fixture_preparation_bindings")
    op.drop_table("quality_http_fixture_preparations")
