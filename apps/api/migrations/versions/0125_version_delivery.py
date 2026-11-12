"""Atomic Version creation receipts and immutable M1 image bindings."""
from alembic import op
import sqlalchemy as sa

revision = "0125_version_delivery"
down_revision = "0124_conversation_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_version_project_id", "versions", ["project_id", "id"])
    op.create_table("version_creations",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in
          ("project_id", "version_id", "actor_id", "request_hash", "created_at")],
        sa.UniqueConstraint("version_id"), sa.UniqueConstraint("project_id", "version_id"),
        sa.ForeignKeyConstraint(["project_id", "version_id"], ["versions.project_id", "versions.id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    op.create_table("version_image_bindings",
        sa.Column("version_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in
          ("project_id", "baseline_id", "publication_id", "image_revision_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "version_id"], ["version_creations.project_id", "version_creations.version_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]))
    op.create_index("ix_version_image_bindings_project_id", "version_image_bindings", ["project_id"])
    op.create_table("project_delivery",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("enabled_by_version_id", sa.String(), nullable=False),
        sa.Column("enabled_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "enabled_by_version_id"], ["version_creations.project_id", "version_creations.version_id"]))
    for table in ("version_creations", "version_image_bindings", "project_delivery"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM version_creations")):
        raise RuntimeError("cannot downgrade while Version creation receipts exist")
    for table in ("project_delivery", "version_image_bindings", "version_creations"):
        op.drop_table(table)
    op.drop_constraint("uq_version_project_id", "versions", type_="unique")
