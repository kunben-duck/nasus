"""Immutable publication-bound embedding generations and retrieval provenance."""
from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa

revision = "0054_frozen_retrieval_index"
down_revision = "0053_image_publication"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_index_reservations",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "baseline_id", "publication_id", "image_revision_id", "input_digest", "model_config_digest", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("project_id", "invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]))
    op.create_table("image_index_generations",
        sa.Column("generation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "publication_id", "artifact_ref", "artifact_hash", "created_at")],
        sa.Column("dimensions", sa.Integer(), nullable=False), sa.Column("document_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("dimensions BETWEEN 1 AND 4096 AND document_count BETWEEN 1 AND 4096"),
        sa.UniqueConstraint("project_id", "generation_id"),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_reservations.project_id", "image_index_reservations.invocation_id"]))
    op.create_index("ix_image_index_generations_publication_id", "image_index_generations", ["publication_id"])
    op.create_table("image_index_documents",
        sa.Column("generation_id", sa.String(), primary_key=True), sa.Column("document_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "object_id", "source_revision_id", "binding_id", "document_hash", "vector_hash")],
        sa.Column("text", sa.Text(), nullable=False), sa.Column("embedding", Vector(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_generations.project_id", "image_index_generations.generation_id"]))
    op.execute("CREATE INDEX ix_image_index_document_fts ON image_index_documents USING gin (to_tsvector('simple'::regconfig, text))")
    op.create_table("image_retrieval_runs",
        sa.Column("retrieval_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "generation_id", "publication_id", "actor_id", "scope_fingerprint", "query_hash", "artifact_ref", "artifact_hash", "created_at")],
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_generations.project_id", "image_index_generations.generation_id"]))
    for table in ("image_index_reservations", "image_index_generations", "image_index_documents", "image_retrieval_runs"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_index_reservations")):
        raise RuntimeError("cannot downgrade while index egress reservations exist")
    for table in ("image_retrieval_runs", "image_index_documents", "image_index_generations", "image_index_reservations"):
        op.drop_table(table)
