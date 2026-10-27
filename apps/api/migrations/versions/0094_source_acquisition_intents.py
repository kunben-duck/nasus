"""Immutable canonical acquisition admission; no invented historical intents."""
from alembic import op
import sqlalchemy as sa

revision = "0094_source_acquisition_intents"
down_revision = "0093_source_tracked_refs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("source_acquisition_intents",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("user_identities.user_id"), nullable=False),
        sa.Column("command_hash", sa.String(), nullable=False),
        sa.Column("selection_mode", sa.String(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("origin_manifest_id", sa.String(), nullable=True),
        sa.Column("origin_manifest_hash", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "origin_manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        sa.CheckConstraint("selection_mode IN ('selected', 'whole_project')", name="ck_source_acquisition_mode"),
        sa.CheckConstraint("(origin_manifest_id IS NULL) = (origin_manifest_hash IS NULL)", name="ck_source_acquisition_origin"))
    op.create_index("ix_source_acquisition_intents_project_id", "source_acquisition_intents", ["project_id"])
    op.execute("CREATE TRIGGER immutable_source_acquisition_intents BEFORE UPDATE OR DELETE ON source_acquisition_intents "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM source_acquisition_intents)")):
        raise RuntimeError("Cannot discard populated source acquisition history.")
    op.drop_table("source_acquisition_intents")
