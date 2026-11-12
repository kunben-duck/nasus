"""Append-only, version-scoped requirement intake; no implicit approval."""
from alembic import op
import sqlalchemy as sa

revision = "0126_requirement_revisions"
down_revision = "0125_version_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in
          ("project_id", "version_id", "us_id", "image_revision_id", "invocation_id", "actor_id", "request_hash", "content_hash")],
        sa.Column("previous_revision_id", sa.String(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "version_id", "us_id", "revision_id"),
        sa.UniqueConstraint("us_id", "sequence"), sa.UniqueConstraint("invocation_id"),
        sa.CheckConstraint("sequence >= 1"),
        sa.ForeignKeyConstraint(["project_id", "version_id"], ["versions.project_id", "versions.id"]),
        sa.ForeignKeyConstraint(["us_id"], ["us_work_items.id"]),
        sa.ForeignKeyConstraint(["project_id", "version_id", "us_id", "previous_revision_id"],
            ["requirement_revisions.project_id", "requirement_revisions.version_id", "requirement_revisions.us_id", "requirement_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    for key in ("project_id", "version_id", "us_id"):
        op.create_index("ix_requirement_revisions_" + key, "requirement_revisions", [key])
    op.execute("CREATE TRIGGER immutable_requirement_revisions BEFORE UPDATE OR DELETE ON requirement_revisions "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM requirement_revisions")):
        raise RuntimeError("cannot discard requirement revision history")
    op.drop_table("requirement_revisions")
