"""Append-only working image adoption, separate from the initial baseline."""
from alembic import op
import sqlalchemy as sa

revision = "0128_iteration_image_adoptions"
down_revision = "0127_requirement_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("version_image_adoptions",
        sa.Column("adoption_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "invocation_id", "project_id", "version_id", "image_revision_id", "parent_image_revision_id",
            "actor_id", "recorded_at", "request_hash", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("invocation_id"),
        sa.UniqueConstraint("project_id", "version_id", "parent_image_revision_id"),
        sa.ForeignKeyConstraint(["project_id", "version_id"], ["version_creations.project_id", "version_creations.version_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    op.execute("CREATE TRIGGER immutable_version_image_adoptions BEFORE UPDATE OR DELETE ON version_image_adoptions "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM version_image_adoptions")):
        raise RuntimeError("cannot discard iteration image adoption history")
    op.drop_table("version_image_adoptions")
