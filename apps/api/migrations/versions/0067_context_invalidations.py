"""Append-only context invalidations and complete fixed dependency edges."""
from alembic import op
import sqlalchemy as sa

revision = "0067_context_invalidations"
down_revision = "0066_mapping_part_staging"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_context_project_pin", "system_image_context_packs", ["project_id", "context_id"])
    op.create_table("system_image_context_invalidations",
        sa.Column("invalidation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "context_id", "binding_id",
            "before_revision_id", "after_revision_id", "invocation_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        *[sa.ForeignKeyConstraint(["project_id", "binding_id", key],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"])
            for key in ("before_revision_id", "after_revision_id")])
    op.create_index("ix_system_image_context_invalidations_project_id", "system_image_context_invalidations", ["project_id"])
    op.create_index("ix_system_image_context_invalidations_context_id", "system_image_context_invalidations", ["context_id"])
    op.create_table("system_image_context_invalidation_nodes",
        sa.Column("invalidation_id", sa.String(), primary_key=True), sa.Column("node_key", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("kind", "artifact_id", "artifact_hash")],
        sa.ForeignKeyConstraint(["invalidation_id"], ["system_image_context_invalidations.invalidation_id"]),
        sa.CheckConstraint("kind IN ('context', 'scope', 'generation', 'case', 'coverage', 'mapping')"))
    op.create_table("system_image_context_invalidation_edges",
        *[sa.Column(key, sa.String(), primary_key=True) for key in ("invalidation_id", "node_key", "parent_key")],
        *[sa.ForeignKeyConstraint(["invalidation_id", key],
            ["system_image_context_invalidation_nodes.invalidation_id", "system_image_context_invalidation_nodes.node_key"])
            for key in ("node_key", "parent_key")])
    for table in ("system_image_context_invalidations", "system_image_context_invalidation_nodes", "system_image_context_invalidation_edges"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM system_image_context_invalidations")):
        raise RuntimeError("cannot downgrade while context invalidations exist")
    for table in ("system_image_context_invalidation_edges", "system_image_context_invalidation_nodes", "system_image_context_invalidations"):
        op.drop_table(table)
    op.drop_constraint("uq_context_project_pin", "system_image_context_packs", type_="unique")
