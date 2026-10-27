"""Append-only context-to-object provenance bridge, retaining both v1 graphs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0071_context_provenance"
down_revision = "0070_object_provenance"
branch_labels = None
depends_on = None

TABLE = "system_image_context_provenance_anchors"
PIN = "uq_derivation_registration_pin"


def upgrade():
    op.create_unique_constraint(PIN, "system_image_derivations", ["project_id", "context_id", "node_key", "content_hash"])
    op.create_table(TABLE,
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "context_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "context_node_key", "context_registration_hash", "image_revision_id", "image_node_key",
            "image_artifact_hash", "image_provenance_hash", "manifest_id", "manifest_hash",
            "input_digest", "query_scope_fingerprint", "content_hash", "policy_revision")),
        sa.ForeignKeyConstraint(["project_id", "context_id", "context_node_key", "context_registration_hash"],
            ["system_image_derivations.project_id", "system_image_derivations.context_id",
             "system_image_derivations.node_key", "system_image_derivations.content_hash"]),
        sa.ForeignKeyConstraint(["project_id", "image_node_key", "image_provenance_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_object_provenance_roots.project_id", "image_object_provenance_roots.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "context_id", "manifest_id"],
            ["system_image_context_query_scopes.project_id", "system_image_context_query_scopes.context_id",
             "system_image_context_query_scopes.manifest_id"]),
        sa.CheckConstraint("context_node_key = 'context:' || context_id"),
        sa.CheckConstraint("image_node_key = 'image_objects:' || image_revision_id"),
        sa.CheckConstraint("policy_revision = 'nasus.context-provenance-anchor.v1'"))
    op.create_index("ix_context_provenance_image", TABLE, ["project_id", "image_revision_id", "context_id"])
    from apps.api.app.infrastructure.persistence.context_provenance_projection_v1 import ContextProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        ContextProvenanceProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_context_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'context provenance anchors are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(f"CREATE TRIGGER immutable_{TABLE} BEFORE UPDATE OR DELETE ON {TABLE} "
               "FOR EACH ROW EXECUTE FUNCTION nasus_reject_context_provenance_mutation()")


def downgrade():
    if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {TABLE})")).scalar():
        raise RuntimeError("Cannot discard registered context provenance anchors.")
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION nasus_reject_context_provenance_mutation()")
    op.drop_constraint(PIN, "system_image_derivations", type_="unique")
