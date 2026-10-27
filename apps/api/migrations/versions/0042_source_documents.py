"""Persist evidenced requirement/test projections and freeze their image membership."""
from alembic import op
import sqlalchemy as sa

revision = "0042_source_documents"
down_revision = "0041_build_authorizations"
branch_labels = None
depends_on = None

OLD_PIN = "(kind = 'code_entity' AND binding_id IS NOT NULL AND entity_id IS NOT NULL AND entity_revision_id IS NOT NULL AND source_revision_id IS NOT NULL) OR (kind = 'legacy_observation' AND binding_id IS NULL AND entity_id IS NULL AND entity_revision_id IS NULL AND source_revision_id IS NULL)"
NEW_PIN = "(kind = 'code_entity' AND binding_id IS NOT NULL AND entity_id IS NOT NULL AND entity_revision_id IS NOT NULL AND source_revision_id IS NOT NULL AND document_revision_id IS NULL) OR (kind = 'source_document' AND binding_id IS NOT NULL AND source_revision_id IS NOT NULL AND document_revision_id IS NOT NULL AND entity_id IS NULL AND entity_revision_id IS NULL) OR (kind = 'legacy_observation' AND binding_id IS NULL AND entity_id IS NULL AND entity_revision_id IS NULL AND source_revision_id IS NULL AND document_revision_id IS NULL)"


def strings(*names):
    return [sa.Column(name, sa.String(), nullable=False) for name in names]


def revision_fk():
    return sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
        ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"])


def upgrade():
    op.create_table("source_document_identities", sa.Column("entity_id", sa.String(), primary_key=True),
        *strings("project_id", "binding_id", "identity_hash", "created_at"), sa.Column("identity_key", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "identity_hash"), sa.UniqueConstraint("project_id", "binding_id", "entity_id"),
        sa.ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]))
    op.create_table("source_document_revisions", sa.Column("document_revision_id", sa.String(), primary_key=True),
        *strings("project_id", "binding_id", "source_revision_id", "entity_id", "title", "kind", "payload_ref", "payload_hash", "captured_at"),
        sa.UniqueConstraint("entity_id", "source_revision_id", "payload_hash"),
        sa.UniqueConstraint("project_id", "binding_id", "source_revision_id", "document_revision_id"), revision_fk(),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "entity_id"],
            ["source_document_identities.project_id", "source_document_identities.binding_id", "source_document_identities.entity_id"]))
    op.create_table("source_document_evidence",
        sa.Column("document_revision_id", sa.String(), primary_key=True), sa.Column("evidence_id", sa.String(), primary_key=True),
        *strings("project_id", "binding_id", "source_revision_id"),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "document_revision_id"],
            ["source_document_revisions.project_id", "source_document_revisions.binding_id", "source_document_revisions.source_revision_id", "source_document_revisions.document_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "evidence_id"],
            ["source_evidence.project_id", "source_evidence.binding_id", "source_evidence.source_revision_id", "source_evidence.evidence_id"]))
    op.create_table("source_document_extractions", sa.Column("extraction_id", sa.String(), primary_key=True),
        *strings("project_id", "binding_id", "source_revision_id", "report_ref", "report_hash", "captured_at"),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "source_revision_id", "report_hash"), revision_fk())
    for table in ("source_document_identities", "source_document_revisions", "source_document_evidence", "source_document_extractions"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.add_column("knowledge_objects", sa.Column("document_reference", sa.JSON(), nullable=True))
    op.add_column("image_object_members", sa.Column("document_revision_id", sa.String(), nullable=True))
    for check in sa.inspect(op.get_bind()).get_check_constraints("image_object_members"):
        # 0038 created two anonymous constraints; use introspection, not a
        # PostgreSQL-generated name which may differ across installations.
        if "kind" in check["sqltext"]:
            op.drop_constraint(check["name"], "image_object_members", type_="check")
    op.create_check_constraint("ck_image_document_kind", "image_object_members", "kind IN ('code_entity', 'source_document', 'legacy_observation')")
    op.create_check_constraint("ck_image_document_pin", "image_object_members", NEW_PIN)
    op.create_foreign_key("fk_image_document_revision", "image_object_members", "source_document_revisions",
        ["project_id", "binding_id", "source_revision_id", "document_revision_id"],
        ["project_id", "binding_id", "source_revision_id", "document_revision_id"])


def downgrade():
    # Never silently discard frozen document membership on a downgrade.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_object_members WHERE kind = 'source_document'")):
        raise RuntimeError("cannot downgrade while source document image members exist")
    op.drop_constraint("fk_image_document_revision", "image_object_members", type_="foreignkey")
    op.drop_constraint("ck_image_document_pin", "image_object_members", type_="check")
    op.drop_constraint("ck_image_document_kind", "image_object_members", type_="check")
    op.create_check_constraint("ck_image_legacy_kind", "image_object_members", "kind IN ('code_entity', 'legacy_observation')")
    op.create_check_constraint("ck_image_legacy_pin", "image_object_members", OLD_PIN)
    op.drop_column("image_object_members", "document_revision_id")
    op.drop_column("knowledge_objects", "document_reference")
    for table in ("source_document_extractions", "source_document_evidence", "source_document_revisions", "source_document_identities"):
        op.drop_table(table)
