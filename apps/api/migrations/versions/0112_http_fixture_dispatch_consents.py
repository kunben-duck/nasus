"""Transaction-bound original fixture consent; no historical authority backfill."""
from alembic import op
import sqlalchemy as sa

revision = "0112_fixture_dispatch_consents"
down_revision = "0111_http_fixture_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_fixture_ownership_project_claim", "quality_http_fixture_dispatch_ownership",
        ["project_id", "claim_id"])
    op.create_table("quality_http_fixture_dispatch_consents", sa.Column("claim_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "grant_id", "grant_digest", "operation", "scope_digest", "source_scope_digest",
            "dispatch_digest", "recorded_at", "consumed_at")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        sa.ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatch_ownership.project_id", "quality_http_fixture_dispatch_ownership.claim_id"]),
        sa.ForeignKeyConstraint(["project_id", "grant_id"],
            ["quality_http_fixture_grants.project_id", "quality_http_fixture_grants.record_id"]),
        sa.CheckConstraint("operation IN ('setup', 'cleanup')"))
    op.execute("CREATE TRIGGER immutable_quality_http_fixture_dispatch_consents BEFORE UPDATE OR DELETE "
        "ON quality_http_fixture_dispatch_consents FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_http_fixture_dispatch_consents)")):
        raise RuntimeError("Cannot discard populated original fixture dispatch consent.")
    op.drop_table("quality_http_fixture_dispatch_consents")
    op.drop_constraint("uq_fixture_ownership_project_claim", "quality_http_fixture_dispatch_ownership", type_="unique")
