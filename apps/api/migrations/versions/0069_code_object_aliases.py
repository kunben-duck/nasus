"""Audited immutable aliases for provider-neutral public code object IDs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0069_code_object_aliases"
down_revision = "0068_derivation_registry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_code_alias_mapping_pin", "code_entity_provider_bindings",
        ["project_id", "binding_id", "source_revision_id", "extraction_digest", "provider_node_hash", "entity_revision_id", "legacy_object_id"])
    op.create_unique_constraint("uq_code_alias_revision_pin", "code_entity_revisions",
        ["project_id", "binding_id", "source_revision_id", "entity_revision_id", "entity_id"])
    op.create_table("code_object_aliases",
        *(sa.Column(name, sa.String(), primary_key=True) for name in
          ("project_id", "binding_id", "source_revision_id", "extraction_digest", "provider_node_hash")),
        *(sa.Column(name, sa.String(), nullable=False) for name in
          ("entity_id", "entity_revision_id", "legacy_object_id", "canonical_object_id", "policy_version", "content_hash")),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "extraction_digest", "provider_node_hash", "entity_revision_id", "legacy_object_id"],
            ["code_entity_provider_bindings.project_id", "code_entity_provider_bindings.binding_id",
             "code_entity_provider_bindings.source_revision_id", "code_entity_provider_bindings.extraction_digest",
             "code_entity_provider_bindings.provider_node_hash", "code_entity_provider_bindings.entity_revision_id", "code_entity_provider_bindings.legacy_object_id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "entity_revision_id", "entity_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id", "code_entity_revisions.entity_id"]),
        sa.CheckConstraint("canonical_object_id = 'CODE-' || entity_id"),
        sa.CheckConstraint("policy_version = 'nasus.code-object-alias.v1'"))
    op.create_index("ix_code_alias_legacy_scope", "code_object_aliases", ["project_id", "source_revision_id", "legacy_object_id", "entity_revision_id"])
    op.create_index("ix_code_alias_canonical_scope", "code_object_aliases", ["project_id", "source_revision_id", "canonical_object_id", "entity_revision_id"])
    from apps.api.app.infrastructure.persistence.code_alias_projection_v1 import CodeAliasProjectorV1
    with Session(bind=op.get_bind()) as session:
        CodeAliasProjectorV1().backfill(session)
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_code_alias_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'code object aliases are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""CREATE TRIGGER immutable_code_object_aliases BEFORE UPDATE OR DELETE ON code_object_aliases
        FOR EACH ROW EXECUTE FUNCTION nasus_reject_code_alias_mutation()""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM code_object_aliases)")).scalar():
        raise RuntimeError("Cannot discard registered code object aliases.")
    op.drop_table("code_object_aliases")
    op.execute("DROP FUNCTION nasus_reject_code_alias_mutation()")
    op.drop_constraint("uq_code_alias_revision_pin", "code_entity_revisions", type_="unique")
    op.drop_constraint("uq_code_alias_mapping_pin", "code_entity_provider_bindings", type_="unique")
