"""Durable code projection pins and PostgreSQL-fenced worker attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0079_code_index_generations"
down_revision = "0078_retrieval_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("code_index_generations",
        sa.Column("generation_id", sa.String(), primary_key=True),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "binding_id", "source_revision_id",
            "source_manifest_hash", "snapshot_hash", "provider_fingerprint", "invocation_id", "content_hash")),
        sa.UniqueConstraint("project_id", "generation_id"),
        sa.UniqueConstraint("source_revision_id", "provider_fingerprint", "invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    op.create_table("code_index_worker_leases",
        sa.Column("generation_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False), sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False), sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["code_index_generations.project_id", "code_index_generations.generation_id"]),
        sa.CheckConstraint("epoch >= 0"),
        sa.CheckConstraint("state IN ('idle', 'preparing', 'ready', 'degraded', 'cancel_requested', 'cancelled', 'failed')"),
        sa.CheckConstraint("(owner_id IS NULL) = (lease_until IS NULL)"),
        sa.CheckConstraint("(state IN ('preparing', 'ready', 'degraded', 'cancel_requested')) = (owner_id IS NOT NULL)"))
    op.create_table("code_index_worker_attempts",
        sa.Column("generation_id", sa.String(), primary_key=True), sa.Column("epoch", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False), sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["code_index_generations.project_id", "code_index_generations.generation_id"]),
        sa.CheckConstraint("epoch > 0"))
    op.create_table("code_index_projection_pins",
        sa.Column("generation_id", sa.String(), primary_key=True),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "projection_hash", "provider_version")),
        sa.Column("entity_count", sa.Integer(), nullable=False), sa.Column("relationship_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["code_index_generations.project_id", "code_index_generations.generation_id"]),
        sa.CheckConstraint("entity_count >= 0 AND relationship_count >= 0"))
    op.execute("""
        CREATE FUNCTION nasus_reject_code_index_pin_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'code index pins and attempts are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("code_index_generations", "code_index_worker_attempts", "code_index_projection_pins"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_code_index_pin_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM code_index_generations)")):
        raise RuntimeError("Cannot discard durable code index pins.")
    for table in ("code_index_projection_pins", "code_index_worker_attempts", "code_index_worker_leases", "code_index_generations"):
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_reject_code_index_pin_mutation()")
