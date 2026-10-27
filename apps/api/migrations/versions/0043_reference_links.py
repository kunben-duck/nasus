"""Persist source-pinned explicit reference candidates, never inferred coverage."""
from alembic import op
import sqlalchemy as sa

revision = "0043_reference_links"
down_revision = "0042_source_documents"
branch_labels = None
depends_on = None


def strings(*names):
    return [sa.Column(name, sa.String(), nullable=False) for name in names]


def upgrade():
    op.create_unique_constraint("uq_image_reference_endpoint", "image_object_members", ["image_revision_id", "object_id", "document_revision_id"])
    op.create_table("image_reference_proposals", sa.Column("proposal_id", sa.String(), primary_key=True),
        *strings("project_id", "image_revision_id", "image_artifact_hash", "content_hash", "method_version", "created_at", "created_by"),
        sa.Column("document_count", sa.Integer(), nullable=False), sa.Column("gaps", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "proposal_id"), sa.UniqueConstraint("project_id", "content_hash"),
        sa.UniqueConstraint("project_id", "proposal_id", "image_revision_id"),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]))
    op.create_index("ix_image_reference_proposals_project_id", "image_reference_proposals", ["project_id"])
    op.create_table("image_reference_assertions", sa.Column("assertion_id", sa.String(), primary_key=True),
        *strings("project_id", "proposal_id", "image_revision_id", "subject_object_id", "subject_revision_id", "object_id",
                 "object_revision_id", "reference_id", "predicate", "semantic_kind", "status", "applicability"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("subject_evidence_ids", sa.JSON(), nullable=False), sa.Column("object_evidence_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("proposal_id", "ordinal"),
        sa.ForeignKeyConstraint(["project_id", "proposal_id", "image_revision_id"], ["image_reference_proposals.project_id", "image_reference_proposals.proposal_id", "image_reference_proposals.image_revision_id"]),
        sa.ForeignKeyConstraint(["image_revision_id", "subject_object_id", "subject_revision_id"], ["image_object_members.image_revision_id", "image_object_members.object_id", "image_object_members.document_revision_id"]),
        sa.ForeignKeyConstraint(["image_revision_id", "object_id", "object_revision_id"], ["image_object_members.image_revision_id", "image_object_members.object_id", "image_object_members.document_revision_id"]),
        sa.CheckConstraint("predicate = 'references' AND semantic_kind = 'observed' AND status = 'proposed'"))
    op.create_table("image_reference_proposal_invocations", sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        *strings("project_id", "proposal_id"),
        sa.ForeignKeyConstraint(["project_id", "proposal_id"], ["image_reference_proposals.project_id", "image_reference_proposals.proposal_id"]))
    for table in ("image_reference_proposals", "image_reference_assertions", "image_reference_proposal_invocations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_reference_proposals")):
        raise RuntimeError("cannot downgrade while reference proposals exist")
    for table in ("image_reference_proposal_invocations", "image_reference_assertions", "image_reference_proposals"):
        op.drop_table(table)
    op.drop_constraint("uq_image_reference_endpoint", "image_object_members", type_="unique")
