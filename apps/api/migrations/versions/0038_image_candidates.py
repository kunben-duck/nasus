"""Freeze source-pinned candidate projections without publishing an Official head."""

from alembic import op
import sqlalchemy as sa

revision = "0038_image_candidates"
down_revision = "0037_code_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_code_revision_complete_pin", "code_entity_revisions",
        ["project_id", "binding_id", "entity_id", "source_revision_id", "entity_revision_id"])
    op.create_unique_constraint("uq_manifest_source_pin", "source_manifest_members",
        ["project_id", "manifest_id", "binding_id", "source_revision_id"])
    op.create_table("image_revisions",
        sa.Column("image_revision_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "baseline_id", "manifest_id", "manifest_hash", "artifact_ref", "artifact_hash",
            "membership_hash", "policy_version", "recorded_at", "status")),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in ("object_count", "code_member_count", "relationship_count")),
        sa.UniqueConstraint("project_id", "image_revision_id"),
        sa.UniqueConstraint("project_id", "image_revision_id", "manifest_id"),
        sa.UniqueConstraint("project_id", "baseline_id", "manifest_id", "artifact_hash"),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        sa.CheckConstraint("status = 'candidate'"),
    )
    op.create_index("ix_image_revisions_project_id", "image_revisions", ["project_id"])
    op.create_table("image_object_members",
        sa.Column("image_revision_id", sa.String(), primary_key=True), sa.Column("object_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "manifest_id", "object_hash", "kind")),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        *(sa.Column(name, sa.String(), nullable=True) for name in ("binding_id", "entity_id", "entity_revision_id", "source_revision_id")),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        sa.ForeignKeyConstraint(["project_id", "manifest_id", "binding_id", "source_revision_id"],
            ["source_manifest_members.project_id", "source_manifest_members.manifest_id",
             "source_manifest_members.binding_id", "source_manifest_members.source_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "entity_id", "source_revision_id", "entity_revision_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id", "code_entity_revisions.entity_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id"]),
        sa.CheckConstraint("kind IN ('code_entity', 'legacy_observation')"),
        sa.CheckConstraint("(kind = 'code_entity' AND binding_id IS NOT NULL AND entity_id IS NOT NULL AND entity_revision_id IS NOT NULL AND source_revision_id IS NOT NULL) OR (kind = 'legacy_observation' AND binding_id IS NULL AND entity_id IS NULL AND entity_revision_id IS NULL AND source_revision_id IS NULL)"),
    )
    op.create_table("image_revision_invocations",
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "image_revision_id", "invocation_id")),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    op.execute("""CREATE FUNCTION nasus_reject_image_revision_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'image candidates are append-only' USING ERRCODE = '23514'; END;
        $$ LANGUAGE plpgsql""")
    for table in ("image_revisions", "image_object_members", "image_revision_invocations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade() -> None:
    for table in ("image_revision_invocations", "image_object_members", "image_revisions"):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_image_revision_mutation()")
    op.drop_constraint("uq_manifest_source_pin", "source_manifest_members", type_="unique")
    op.drop_constraint("uq_code_revision_complete_pin", "code_entity_revisions", type_="unique")
