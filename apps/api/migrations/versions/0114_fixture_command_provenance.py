"""Original fixture command bindings, never backfilled from private dispatches."""
from alembic import op
import sqlalchemy as sa

revision = "0114_fixture_command_provenance"
down_revision = "0113_fixture_native_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_http_fixture_commands", sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "grant_id", "grant_digest",
            "request_digest", "actor_id", "operation", "scope_digest", "source_scope_digest", "work_id", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("grant_id"), sa.UniqueConstraint("work_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "grant_id"],
            ["quality_http_fixture_grants.project_id", "quality_http_fixture_grants.record_id"]),
        sa.CheckConstraint("operation IN ('setup', 'cleanup')"))
    op.create_table("quality_http_fixture_dispatch_commands", sa.Column("claim_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "invocation_id", "intent_digest",
            "request_digest", "dispatch_digest", "recorded_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_commands.project_id", "quality_http_fixture_commands.invocation_id"]))
    for table in ("quality_http_fixture_commands", "quality_http_fixture_dispatch_commands"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_http_fixture_dispatch_commands", "quality_http_fixture_commands"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated original fixture command provenance.")
    op.drop_table("quality_http_fixture_dispatch_commands")
    op.drop_table("quality_http_fixture_commands")
