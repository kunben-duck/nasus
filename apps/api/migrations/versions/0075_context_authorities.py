"""Exact archived authority dependencies and an explicit historical backfill inventory."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0075_context_authorities"
down_revision = "0074_authority_provenance"
branch_labels = None
depends_on = None

ROOT = "system_image_context_authority_roots"
EDGE = "system_image_context_authority_dependencies"
TARGET = "system_image_context_authority_backfill_targets"
POLICY = "nasus.context-authority-dependencies.v1"


def upgrade():
    op.create_table(ROOT,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "context_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("image_revision_id", "image_artifact_hash",
            "input_digest", "artifact_hash", "invocation_id", "context_metadata_hash", "registration_invocation_id",
            "registered_by", "registered_at", "policy_revision")),
        sa.Column("authority_count", sa.Integer(), nullable=False),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("authority_pins_hash", "content_hash")),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["registration_invocation_id"], ["tool_invocations.id"]),
        sa.CheckConstraint("authority_count BETWEEN 0 AND 256"),
        sa.CheckConstraint("policy_revision = 'nasus.context-authority-dependencies.v1'"))
    op.create_index("ix_context_authority_roots_image", ROOT, ["project_id", "image_revision_id", "context_id"])
    op.create_table(EDGE,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "context_id", "object_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("kind", "basis_digest", "status")),
        *(sa.Column(key, sa.String(), nullable=True) for key in ("revision_id", "artifact_hash", "authority_registration_hash")),
        *(sa.Column(key, sa.String(), nullable=False) for key in (
            "image_revision_id", "member_provenance_hash", "member_node_key", "policy_revision", "content_hash")),
        sa.ForeignKeyConstraint(["project_id", "context_id"], [f"{ROOT}.project_id", f"{ROOT}.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "kind", "revision_id", "authority_registration_hash"],
            ["requirement_authority_provenance.project_id", "requirement_authority_provenance.kind",
             "requirement_authority_provenance.revision_id", "requirement_authority_provenance.content_hash"]),
        sa.ForeignKeyConstraint(["project_id", "member_node_key", "member_provenance_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        sa.CheckConstraint("kind IN ('acceptance', 'business_rule')"),
        sa.CheckConstraint("(status = 'unapproved' AND revision_id IS NULL AND artifact_hash IS NULL AND authority_registration_hash IS NULL) OR (status IN ('approved', 'withdrawn') AND revision_id IS NOT NULL AND artifact_hash IS NOT NULL AND authority_registration_hash IS NOT NULL)"),
        sa.CheckConstraint("member_node_key = 'member:' || image_revision_id || '/' || object_id"),
        sa.CheckConstraint("policy_revision = 'nasus.context-authority-dependencies.v1'"))
    op.create_index("ix_context_authority_revision", EDGE, ["project_id", "kind", "revision_id", "context_id"])
    op.create_index("ix_context_authority_member", EDGE, ["project_id", "image_revision_id", "object_id", "context_id"])
    op.create_table(TARGET,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "context_id")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("context_metadata_hash", "artifact_hash", "policy_revision")),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.CheckConstraint("policy_revision = 'nasus.context-authority-dependencies.v1'"))
    # Metadata cannot reveal historical authority pins. Enroll exact pre-upgrade
    # archives for a separate authorized read; never fabricate edges in a migration.
    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
    from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
    from apps.api.app.infrastructure.persistence.context_authority_models import ContextAuthorityBackfillTargetRecord
    with Session(bind=op.get_bind()) as session:
        for context in session.scalars(sa.select(ContextPackRecord).execution_options(yield_per=128)):
            if (snapshot_digest(context.payload) != context.content_hash or any(context.payload.get(key) != getattr(context, key)
                    for key in ("project_id", "context_id", "image_revision_id", "invocation_id"))):
                raise RuntimeError("Cannot enroll a corrupt archived context for authority registration.")
            session.add(ContextAuthorityBackfillTargetRecord(project_id=context.project_id, context_id=context.context_id,
                context_metadata_hash=context.content_hash, artifact_hash=context.payload["artifact_hash"], policy_revision=POLICY))
        session.flush()
        session.commit()
    op.execute("""
        CREATE FUNCTION nasus_reject_context_authority_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'context authority dependencies are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in (ROOT, EDGE, TARGET):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_context_authority_mutation()")


def downgrade():
    for table in (ROOT, EDGE, TARGET):
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
            raise RuntimeError("Cannot discard context authority dependencies or pending historical archives.")
    for table in (EDGE, TARGET, ROOT):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_context_authority_mutation()")
