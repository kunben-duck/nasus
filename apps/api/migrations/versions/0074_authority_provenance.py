"""Append-only authority-to-source and predecessor pins, retaining old hashes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0074_authority_provenance"
down_revision = "0073_relation_fact_provenance"
branch_labels = None
depends_on = None

TABLE = "requirement_authority_provenance"


def upgrade():
    op.create_table(TABLE,
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "kind", "revision_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "authority_id", "metadata_hash", "artifact_hash", "image_revision_id", "image_artifact_hash", "object_id",
            "binding_id", "source_revision_id", "document_revision_id", "basis_digest", "invocation_id", "status")),
        sa.Column("sequence", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "image_node_key", "image_provenance_hash", "member_node_key", "member_provenance_hash",
            "document_node_key", "document_provenance_hash")),
        *(sa.Column(name, sa.String(), nullable=True) for name in ("previous_revision_id", "previous_registration_hash",
            "acceptance_revision_id", "business_rule_revision_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("content_hash", "policy_revision")),
        sa.UniqueConstraint("project_id", "kind", "revision_id", "content_hash", name="uq_authority_provenance_pin"),
        sa.ForeignKeyConstraint(["project_id", "authority_id", "acceptance_revision_id"],
            ["quality_acceptance_revisions.project_id", "quality_acceptance_revisions.ac_id", "quality_acceptance_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "authority_id", "business_rule_revision_id"],
            ["quality_business_rule_revisions.project_id", "quality_business_rule_revisions.rule_id", "quality_business_rule_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "kind", "previous_revision_id", "previous_registration_hash"],
            [f"{TABLE}.project_id", f"{TABLE}.kind", f"{TABLE}.revision_id", f"{TABLE}.content_hash"]),
        *[sa.ForeignKeyConstraint(["project_id", key, digest],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"])
          for key, digest in (("image_node_key", "image_provenance_hash"),
                             ("member_node_key", "member_provenance_hash"),
                             ("document_node_key", "document_provenance_hash"))],
        sa.CheckConstraint("(kind = 'acceptance' AND acceptance_revision_id = revision_id AND acceptance_revision_id IS NOT NULL AND business_rule_revision_id IS NULL) OR (kind = 'business_rule' AND business_rule_revision_id = revision_id AND business_rule_revision_id IS NOT NULL AND acceptance_revision_id IS NULL)"),
        sa.CheckConstraint("status IN ('approved', 'withdrawn') AND sequence BETWEEN 1 AND 1000"),
        sa.CheckConstraint("(sequence = 1 AND status = 'approved' AND previous_revision_id IS NULL AND previous_registration_hash IS NULL) OR (sequence > 1 AND previous_revision_id IS NOT NULL AND previous_registration_hash IS NOT NULL AND previous_revision_id <> revision_id)"),
        sa.CheckConstraint("image_node_key = 'image_objects:' || image_revision_id"),
        sa.CheckConstraint("member_node_key = 'member:' || image_revision_id || '/' || object_id"),
        sa.CheckConstraint("document_node_key = 'document:' || document_revision_id"),
        sa.CheckConstraint("policy_revision = 'nasus.requirement-authority-provenance.v1'"))
    op.create_index("ix_authority_provenance_source", TABLE,
        ["project_id", "binding_id", "source_revision_id", "kind", "revision_id"])
    op.create_index("ix_authority_provenance_member", TABLE,
        ["project_id", "image_revision_id", "object_id", "kind", "sequence"])
    from apps.api.app.infrastructure.persistence.authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        AuthorityProvenanceProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_authority_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'authority provenance anchors are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(f"CREATE TRIGGER immutable_{TABLE} BEFORE UPDATE OR DELETE ON {TABLE} "
               "FOR EACH ROW EXECUTE FUNCTION nasus_reject_authority_provenance_mutation()")


def downgrade():
    if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {TABLE})")).scalar():
        raise RuntimeError("Cannot discard registered authority provenance anchors.")
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION nasus_reject_authority_provenance_mutation()")
