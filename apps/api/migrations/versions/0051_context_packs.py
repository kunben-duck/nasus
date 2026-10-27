"""Persist immutable, source-pinned test-design context derivations."""
from alembic import op
import sqlalchemy as sa

revision = "0051_context_packs"
down_revision = "0050_acceptance_authority"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("system_image_context_packs",
        sa.Column("context_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "image_revision_id", "invocation_id", "request_hash", "content_hash", "artifact_ref")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]))
    op.execute("CREATE TRIGGER immutable_system_image_context_packs BEFORE UPDATE OR DELETE ON system_image_context_packs FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM system_image_context_packs")):
        raise RuntimeError("cannot downgrade while context derivations exist")
    op.drop_table("system_image_context_packs")
