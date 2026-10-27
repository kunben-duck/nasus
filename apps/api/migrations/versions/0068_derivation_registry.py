"""Complete metadata derivations and frozen source query scopes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0068_derivation_registry"
down_revision = "0067_context_invalidations"
branch_labels = None
depends_on = None

TABLES = ("system_image_derivations", "system_image_derivation_edges",
    "system_image_context_query_scopes", "system_image_context_query_sources")


def upgrade():
    # Freeze the original DDL: future ORM constraints must not be created before
    # their own migration (0071 adds a hash-pinned registration constraint).
    from apps.api.app.infrastructure.persistence.derivation_registry_projection import DerivationRegistryProjector
    connection = op.get_bind()
    op.create_table(TABLES[0],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "node_key")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("context_id", "kind", "artifact_id",
            "artifact_hash", "invocation_id", "policy_revision", "content_hash")),
        sa.UniqueConstraint("project_id", "context_id", "node_key", name="uq_derivation_context_node"),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.CheckConstraint("kind IN ('context', 'scope', 'generation', 'case', 'coverage', 'mapping')"),
        sa.CheckConstraint("node_key = kind || ':' || artifact_id"))
    op.create_index("ix_derivation_context_kind", TABLES[0], ["project_id", "context_id", "kind", "artifact_id"])
    op.create_table(TABLES[1],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "node_key", "parent_key")),
        sa.Column("context_id", sa.String(), nullable=False),
        *[sa.ForeignKeyConstraint(["project_id", "context_id", key],
            ["system_image_derivations.project_id", "system_image_derivations.context_id", "system_image_derivations.node_key"])
          for key in ("node_key", "parent_key")],
        sa.CheckConstraint("node_key <> parent_key"))
    op.create_index("ix_derivation_reverse_parent", TABLES[1], ["project_id", "parent_key", "node_key"])
    op.create_table(TABLES[2],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "context_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("image_revision_id", "image_artifact_hash",
            "manifest_id", "manifest_hash", "input_digest", "query_scope_fingerprint", "source_members_hash")),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "context_id", "manifest_id", name="uq_query_scope_manifest_pin"),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        sa.CheckConstraint("member_count > 0"))
    op.create_table(TABLES[3],
        *(sa.Column(name, sa.String(), primary_key=True) for name in ("project_id", "context_id", "binding_id")),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("manifest_id", "source_type")),
        sa.Column("source_revision_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "context_id", "manifest_id"],
            ["system_image_context_query_scopes.project_id", "system_image_context_query_scopes.context_id", "system_image_context_query_scopes.manifest_id"]),
        sa.ForeignKeyConstraint(["manifest_id", "binding_id"], ["source_manifest_members.manifest_id", "source_manifest_members.binding_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        sa.CheckConstraint("status IN ('captured', 'failed', 'pending', 'legacy_unverified')"),
        sa.CheckConstraint("(status = 'captured') = (source_revision_id IS NOT NULL)"))
    op.create_index("ix_query_source_reverse_revision", TABLES[3], ["project_id", "binding_id", "source_revision_id", "context_id"])
    with Session(bind=connection) as session:
        DerivationRegistryProjector().backfill(session)
        session.flush()
        session.commit()
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if any(op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {table}")) for table in TABLES):
        raise RuntimeError("cannot downgrade while derivation provenance exists")
    for table in reversed(TABLES):
        op.drop_table(table)
