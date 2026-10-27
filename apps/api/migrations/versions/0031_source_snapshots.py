"""Add immutable source revisions and multi-binding manifests.

Revision ID: 0031_source_snapshots
Revises: 0030_conversation_turns
"""

from alembic import op
import sqlalchemy as sa

revision = "0031_source_snapshots"
down_revision = "0030_conversation_turns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_bindings",
        sa.Column("binding_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("legacy_source_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_identity", sa.String(), nullable=False),
        sa.Column("identity_hash", sa.String(), nullable=False),
        sa.Column("registered_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id"),
        sa.UniqueConstraint("project_id", "legacy_source_id"),
        sa.UniqueConstraint("project_id", "identity_hash"),
        sa.CheckConstraint("kind IN ('code', 'us_doc', 'test_asset')"),
    )
    op.create_index("ix_source_bindings_project_id", "source_bindings", ["project_id"])
    op.create_table(
        "source_revisions",
        sa.Column("source_revision_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("external_revision", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("manifest_hash", sa.String(), nullable=False),
        sa.Column("manifest_ref", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "source_revision_id"),
        sa.UniqueConstraint("binding_id", "external_revision", "manifest_hash"),
        sa.ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
        sa.CheckConstraint("file_count > 0 AND byte_count >= 0"),
    )
    for column in ("project_id", "binding_id"):
        op.create_index(f"ix_source_revisions_{column}", "source_revisions", [column])
    op.create_table(
        "source_manifests",
        sa.Column("manifest_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "manifest_id"),
        sa.UniqueConstraint("project_id", "content_hash"),
    )
    for column in ("project_id", "captured_at"):
        op.create_index(f"ix_source_manifests_{column}", "source_manifests", [column])
    op.create_table(
        "source_manifest_members",
        sa.Column("manifest_id", sa.String(), primary_key=True),
        sa.Column("binding_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_revision_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
        sa.CheckConstraint("status IN ('captured', 'failed', 'pending', 'legacy_unverified')"),
        sa.CheckConstraint("(status = 'captured') = (source_revision_id IS NOT NULL)"),
    )
    op.create_table(
        "source_manifest_heads",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("manifest_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
    )
    # Old rows have no verified raw snapshot. They are imported lazily as
    # bindings; only a new successful capture can create a verified revision.
    op.execute("""
        CREATE FUNCTION nasus_reject_source_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'source snapshot history is append-only'
                USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("source_revisions", "source_manifests", "source_manifest_members"):
        op.execute(f"""
            CREATE TRIGGER immutable_{table}
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION nasus_reject_source_snapshot_mutation()
        """)


def downgrade() -> None:
    for table in ("source_manifest_heads", "source_manifest_members", "source_manifests", "source_revisions", "source_bindings"):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_source_snapshot_mutation()")
