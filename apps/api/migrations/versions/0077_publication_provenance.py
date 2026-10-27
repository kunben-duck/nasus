"""Connect native publication, review and context ancestry without rewriting facts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0077_publication_provenance"
down_revision = "0076_image_rollback"
branch_labels = None
depends_on = None

TABLES = ("image_publication_provenance", "image_publication_dependencies", "context_publication_dependencies")


def upgrade():
    node, edge, context = TABLES
    op.create_table(node,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "kind", "fact_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("baseline_id", "image_revision_id", "image_artifact_hash",
            "manifest_id", "manifest_hash", "metadata_hash", "request_hash", "invocation_id", "image_provenance_hash",
            "relations_provenance_hash", "image_node_key", "relations_node_key", "dependencies_hash", "policy_revision", "content_hash")),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("dependency_count", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.String(), nullable=True), sa.Column("publication_id", sa.String(), nullable=True),
        sa.UniqueConstraint("project_id", "baseline_id", "kind", "fact_id", "content_hash", name="uq_publication_provenance_pin"),
        sa.ForeignKeyConstraint(["project_id", "review_id"], ["image_publication_reviews.project_id", "image_publication_reviews.review_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        *[sa.ForeignKeyConstraint(["project_id", key, digest], [table + ".project_id", table + ".node_key", table + ".content_hash"])
          for key, digest, table in (("image_node_key", "image_provenance_hash", "image_object_provenance_nodes"),
              ("relations_node_key", "relations_provenance_hash", "image_relation_provenance_nodes"))],
        sa.CheckConstraint("(kind = 'review' AND review_id IS NOT NULL AND review_id = fact_id AND publication_id IS NULL) OR (kind = 'publication' AND publication_id IS NOT NULL AND publication_id = fact_id AND review_id IS NULL)"),
        sa.CheckConstraint("sequence > 0 AND dependency_count BETWEEN 0 AND 3"),
        sa.CheckConstraint("image_node_key = 'image_objects:' || image_revision_id AND relations_node_key = 'image_relations:' || image_revision_id"),
        sa.CheckConstraint("policy_revision = 'nasus.publication-provenance.v1'"))
    op.create_index("ix_publication_provenance_image", node, ["project_id", "image_revision_id", "baseline_id", "kind"])
    op.create_table(edge,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "fact_kind", "fact_id", "relation")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("baseline_id", "fact_hash", "parent_kind", "parent_id", "parent_hash")),
        *[sa.ForeignKeyConstraint(["project_id", "baseline_id", prefix + "kind", prefix + "id", prefix + "hash"],
            [node + "." + key for key in ("project_id", "baseline_id", "kind", "fact_id", "content_hash")])
          for prefix in ("fact_", "parent_")],
        sa.CheckConstraint("(relation = 'previous_review' AND fact_kind = 'review' AND parent_kind = 'review') OR (relation = 'expected_head' AND fact_kind = 'review' AND parent_kind = 'publication') OR (relation = 'approval' AND fact_kind = 'publication' AND parent_kind = 'review') OR (relation IN ('previous_publication', 'rollback_source') AND parent_kind = 'publication' AND (relation = 'rollback_source' OR fact_kind = 'publication'))"),
        sa.CheckConstraint("fact_kind <> parent_kind OR fact_id <> parent_id"))
    op.create_index("ix_publication_dependency_parent", edge, ["project_id", "parent_kind", "parent_id"])
    op.create_table(context,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "context_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("context_metadata_hash", "context_request_hash", "image_revision_id",
            "image_artifact_hash", "baseline_id", "publication_kind", "publication_id", "publication_registration_hash", "policy_revision", "content_hash")),
        sa.ForeignKeyConstraint(["project_id", "context_id"], ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "publication_kind", "publication_id", "publication_registration_hash"],
            [node + "." + key for key in ("project_id", "baseline_id", "kind", "fact_id", "content_hash")]),
        sa.CheckConstraint("publication_kind = 'publication' AND policy_revision = 'nasus.publication-provenance.v1'"))
    op.create_index("ix_context_publication_dependency", context, ["project_id", "publication_id", "context_id"])
    from apps.api.app.infrastructure.persistence.publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        PublicationProvenanceProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_publication_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'publication provenance is append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_publication_provenance_mutation()")


def downgrade():
    for table in TABLES:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
            raise RuntimeError("Cannot discard registered publication provenance.")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_publication_provenance_mutation()")
