"""Add a shadow registry of source-pinned, provider-neutral code identities."""

from alembic import op
import sqlalchemy as sa

revision = "0032_code_entity_registry"
down_revision = "0031_source_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_entity_identities",
        sa.Column("entity_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("symbol_key_hash", sa.String(), nullable=False),
        sa.Column("symbol_key", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "entity_id"),
        sa.UniqueConstraint("project_id", "binding_id", "symbol_key_hash"),
        sa.ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
    )
    op.create_table(
        "code_entity_revisions",
        sa.Column("entity_revision_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("source_revision_id", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "source_revision_id", "entity_revision_id"),
        sa.UniqueConstraint("entity_id", "source_revision_id", "payload_hash"),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "entity_id"],
            ["code_entity_identities.project_id", "code_entity_identities.binding_id", "code_entity_identities.entity_id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
    )
    op.create_table(
        "code_entity_provider_bindings",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("binding_id", sa.String(), primary_key=True),
        sa.Column("source_revision_id", sa.String(), primary_key=True),
        sa.Column("extraction_digest", sa.String(), primary_key=True),
        sa.Column("provider_node_hash", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_version", sa.String(), nullable=False),
        sa.Column("provider_node_id", sa.String(), nullable=False),
        sa.Column("entity_revision_id", sa.String(), nullable=False),
        sa.Column("legacy_object_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "entity_revision_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id"],
        ),
    )
    op.create_index("ix_code_entity_provider_bindings_legacy_object_id", "code_entity_provider_bindings", ["legacy_object_id"])
    op.execute("""
        CREATE FUNCTION nasus_reject_code_entity_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'code entity registry history is append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("code_entity_identities", "code_entity_revisions", "code_entity_provider_bindings"):
        op.execute(f"""
            CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION nasus_reject_code_entity_mutation()
        """)


def downgrade() -> None:
    for table in ("code_entity_provider_bindings", "code_entity_revisions", "code_entity_identities"):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_code_entity_mutation()")
