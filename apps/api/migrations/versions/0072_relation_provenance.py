"""Frozen reference/semantic dependency graph and context anchors, without v1 rewrites."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0072_relation_provenance"
down_revision = "0071_context_provenance"
branch_labels = None
depends_on = None

TABLES = ("image_relation_provenance_nodes", "image_relation_provenance_edges",
    "image_relation_provenance_roots", "system_image_context_relation_anchors")


def upgrade():
    op.create_table(TABLES[0],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "node_key")),
        *(sa.Column(name, sa.String(), nullable=False) for name in
          ("kind", "artifact_id", "artifact_hash", "metadata_hash")),
        *(sa.Column(name, sa.String(), nullable=True) for name in ("object_node_key", "object_node_hash")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("content_hash", "policy_revision")),
        sa.UniqueConstraint("project_id", "node_key", "content_hash", name="uq_relation_provenance_node_pin"),
        sa.ForeignKeyConstraint(["project_id", "object_node_key", "object_node_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        sa.CheckConstraint("kind IN ('object_pin', 'reference_proposal', 'reference_assertion', 'reference_decision', "
            "'semantic_evaluation', 'semantic_assertion', 'semantic_decision', 'relation_member', 'image_relations')"),
        sa.CheckConstraint("node_key = kind || ':' || artifact_id"),
        sa.CheckConstraint("policy_revision = 'nasus.image-relation-provenance.v1'"),
        sa.CheckConstraint("(kind = 'object_pin' AND object_node_key = artifact_id AND object_node_key IS NOT NULL "
            "AND object_node_hash IS NOT NULL AND object_node_hash = artifact_hash) OR "
            "(kind <> 'object_pin' AND object_node_key IS NULL AND object_node_hash IS NULL)"))
    op.create_index("ix_relation_provenance_kind", TABLES[0], ["project_id", "kind", "artifact_id"])
    op.create_table(TABLES[1],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "node_key", "parent_key")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("node_hash", "parent_hash")),
        *[sa.ForeignKeyConstraint(["project_id", key, digest],
            ["image_relation_provenance_nodes.project_id", "image_relation_provenance_nodes.node_key",
             "image_relation_provenance_nodes.content_hash"])
          for key, digest in (("node_key", "node_hash"), ("parent_key", "parent_hash"))],
        sa.CheckConstraint("node_key <> parent_key"))
    op.create_index("ix_relation_provenance_reverse", TABLES[1], ["project_id", "parent_key", "node_key"])
    op.create_table(TABLES[2],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "image_revision_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("node_key", "content_hash")),
        sa.UniqueConstraint("project_id", "image_revision_id", "node_key", "content_hash", name="uq_image_relation_root_pin"),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "node_key", "content_hash"],
            ["image_relation_provenance_nodes.project_id", "image_relation_provenance_nodes.node_key",
             "image_relation_provenance_nodes.content_hash"]),
        sa.CheckConstraint("node_key = 'image_relations:' || image_revision_id"))
    op.create_table(TABLES[3],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "context_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("image_revision_id", "image_node_key",
          "image_relations_hash", "source_anchor_hash", "content_hash")),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_provenance_anchors.project_id", "system_image_context_provenance_anchors.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id", "image_node_key", "image_relations_hash"],
            ["image_relation_provenance_roots.project_id", "image_relation_provenance_roots.image_revision_id",
             "image_relation_provenance_roots.node_key", "image_relation_provenance_roots.content_hash"]),
        sa.CheckConstraint("image_node_key = 'image_relations:' || image_revision_id"))
    op.create_index("ix_context_relation_image", TABLES[3], ["project_id", "image_revision_id", "context_id"])
    from apps.api.app.infrastructure.persistence.relation_provenance_projection_v1 import RelationProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        RelationProvenanceProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_relation_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'image relation provenance is append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_relation_provenance_mutation()")


def downgrade():
    if any(op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar() for table in TABLES):
        raise RuntimeError("Cannot discard registered image relation provenance.")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_relation_provenance_mutation()")
