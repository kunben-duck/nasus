"""Immutable, audited image object-source dependency subgraph."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0070_object_provenance"
down_revision = "0069_code_object_aliases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_object_provenance_nodes",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("node_key", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in
          ("kind", "artifact_id", "artifact_hash", "metadata_hash", "content_hash", "policy_revision")),
        sa.Column("source_pins", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "node_key", "content_hash", name="uq_object_provenance_node_pin"),
        sa.CheckConstraint("kind IN ('source', 'manifest', 'code', 'document', 'evidence', 'member', 'image_objects')"),
        sa.CheckConstraint("node_key = kind || ':' || artifact_id"),
        sa.CheckConstraint("policy_revision = 'nasus.image-object-provenance.v1'"))
    op.create_index("ix_object_provenance_kind", "image_object_provenance_nodes", ["project_id", "kind", "artifact_id"])
    op.create_table("image_object_provenance_edges",
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "node_key", "parent_key")),
        sa.Column("node_hash", sa.String(), nullable=False),
        sa.Column("parent_hash", sa.String(), nullable=False),
        *[sa.ForeignKeyConstraint(["project_id", key, digest],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"])
          for key, digest in (("node_key", "node_hash"), ("parent_key", "parent_hash"))],
        sa.CheckConstraint("node_key <> parent_key"))
    op.create_index("ix_object_provenance_reverse", "image_object_provenance_edges", ["project_id", "parent_key", "node_key"])
    op.create_table("image_object_provenance_roots",
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "image_revision_id")),
        sa.Column("node_key", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "node_key", "content_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        sa.CheckConstraint("node_key = 'image_objects:' || image_revision_id"))
    from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        ObjectProvenanceProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_object_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'image object provenance is append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("image_object_provenance_nodes", "image_object_provenance_edges", "image_object_provenance_roots"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_object_provenance_mutation()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM image_object_provenance_nodes)")).scalar():
        raise RuntimeError("Cannot discard registered image object provenance.")
    for table in ("image_object_provenance_roots", "image_object_provenance_edges", "image_object_provenance_nodes"):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_object_provenance_mutation()")
