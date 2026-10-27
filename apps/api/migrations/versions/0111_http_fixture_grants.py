"""Independent bounded operation consent; no grants backfilled from definitions."""
from alembic import op
import sqlalchemy as sa

revision = "0111_http_fixture_grants"
down_revision = "0110_http_fixture_recipes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_http_fixture_recipe_original", "quality_http_fixture_recipes",
        ["project_id", "record_id", "artifact_hash"])
    op.create_table("quality_http_fixture_grants", sa.Column("record_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "recipe_id", "recipe_artifact_hash", "attempt_id", "operation", "invocation_id", "actor_id",
            "recorded_at", "expires_at", "source_scope_digest", "scope_digest", "request_hash", "status")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "record_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "recipe_id", "recipe_artifact_hash"],
            ["quality_http_fixture_recipes.project_id", "quality_http_fixture_recipes.record_id", "quality_http_fixture_recipes.artifact_hash"]),
        sa.CheckConstraint("operation IN ('setup', 'cleanup')"), sa.CheckConstraint("status = 'issued'"))
    op.create_index("ix_http_fixture_grant_attempt", "quality_http_fixture_grants", ["project_id", "attempt_id", "record_id"])
    op.execute("CREATE TRIGGER immutable_quality_http_fixture_grants BEFORE UPDATE OR DELETE "
        "ON quality_http_fixture_grants FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_http_fixture_grants)")):
        raise RuntimeError("Cannot discard populated independent fixture operation consent.")
    op.drop_table("quality_http_fixture_grants")
    op.drop_constraint("uq_http_fixture_recipe_original", "quality_http_fixture_recipes", type_="unique")
