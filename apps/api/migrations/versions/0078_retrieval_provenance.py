"""Pin index and retrieval dependencies to native publication and object ancestry."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0078_retrieval_provenance"
down_revision = "0077_publication_provenance"
branch_labels = None
depends_on = None
TABLES = ("image_retrieval_provenance", "image_index_document_dependencies", "context_retrieval_dependencies")


def upgrade():
    op.create_unique_constraint("uq_frozen_retrieval_project_pin", "image_retrieval_runs", ["project_id", "retrieval_id"])
    node, document, context = TABLES
    op.create_table(node,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "kind", "artifact_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("metadata_hash", "baseline_id", "publication_kind",
            "publication_id", "image_revision_id", "image_artifact_hash", "publication_registration_hash", "documents_hash",
            "policy_revision", "content_hash")),
        *(sa.Column(key, sa.String(), nullable=True) for key in ("parent_kind", "parent_id", "parent_hash",
            "reservation_id", "generation_id", "retrieval_id")),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "kind", "artifact_id", "content_hash", name="uq_retrieval_provenance_pin"),
        sa.ForeignKeyConstraint(["project_id", "reservation_id"], ["image_index_reservations.project_id", "image_index_reservations.invocation_id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_generations.project_id", "image_index_generations.generation_id"]),
        sa.ForeignKeyConstraint(["project_id", "retrieval_id"], ["image_retrieval_runs.project_id", "image_retrieval_runs.retrieval_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "publication_kind", "publication_id", "publication_registration_hash"],
            ["image_publication_provenance." + key for key in ("project_id", "baseline_id", "kind", "fact_id", "content_hash")]),
        sa.ForeignKeyConstraint(["project_id", "parent_kind", "parent_id", "parent_hash"],
            [node + "." + key for key in ("project_id", "kind", "artifact_id", "content_hash")]),
        sa.CheckConstraint("(kind = 'reservation' AND reservation_id = artifact_id AND reservation_id IS NOT NULL AND generation_id IS NULL AND retrieval_id IS NULL AND parent_kind IS NULL AND parent_id IS NULL AND parent_hash IS NULL) OR (kind = 'generation' AND generation_id = artifact_id AND generation_id IS NOT NULL AND reservation_id IS NULL AND retrieval_id IS NULL AND parent_kind IS NOT NULL AND parent_kind = 'reservation' AND parent_id IS NOT NULL AND parent_hash IS NOT NULL) OR (kind = 'retrieval' AND retrieval_id = artifact_id AND retrieval_id IS NOT NULL AND reservation_id IS NULL AND generation_id IS NULL AND parent_kind IS NOT NULL AND parent_kind = 'generation' AND parent_id IS NOT NULL AND parent_hash IS NOT NULL)"),
        sa.CheckConstraint("document_count BETWEEN 0 AND 4096 AND ((kind = 'generation') = (document_count > 0))"),
        sa.CheckConstraint("publication_kind = 'publication' AND policy_revision = 'nasus.retrieval-provenance.v1'"))
    op.create_index("ix_retrieval_provenance_parent", node, ["project_id", "parent_kind", "parent_id"])
    op.create_index("ix_retrieval_provenance_publication", node, ["project_id", "publication_id", "kind"])
    op.create_table(document,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "generation_id", "document_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("generation_kind", "generation_hash", "document_hash", "member_key", "member_hash")),
        sa.ForeignKeyConstraint(["project_id", "generation_kind", "generation_id", "generation_hash"],
            [node + "." + key for key in ("project_id", "kind", "artifact_id", "content_hash")]),
        sa.ForeignKeyConstraint(["generation_id", "document_id"], ["image_index_documents.generation_id", "image_index_documents.document_id"]),
        sa.ForeignKeyConstraint(["project_id", "member_key", "member_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key", "image_object_provenance_nodes.content_hash"]),
        sa.CheckConstraint("generation_kind = 'generation'"))
    op.create_index("ix_index_document_dependency_member", document, ["project_id", "member_key", "generation_id"])
    op.create_table(context,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "context_id", "target_object_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("image_revision_id", "context_metadata_hash",
            "context_request_hash", "retrieval_kind", "retrieval_id", "retrieval_hash", "content_hash")),
        sa.ForeignKeyConstraint(["project_id", "context_id"], ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["image_revision_id", "target_object_id"], ["image_object_members.image_revision_id", "image_object_members.object_id"]),
        sa.ForeignKeyConstraint(["project_id", "retrieval_kind", "retrieval_id", "retrieval_hash"],
            [node + "." + key for key in ("project_id", "kind", "artifact_id", "content_hash")]),
        sa.CheckConstraint("retrieval_kind = 'retrieval'"))
    op.create_index("ix_context_retrieval_dependency", context, ["project_id", "retrieval_id", "context_id"])
    from apps.api.app.infrastructure.persistence.retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        RetrievalProvenanceProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_retrieval_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'retrieval provenance is append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_retrieval_provenance_mutation()")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard registered retrieval provenance.")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_retrieval_provenance_mutation()")
    op.drop_constraint("uq_frozen_retrieval_project_pin", "image_retrieval_runs", type_="unique")
