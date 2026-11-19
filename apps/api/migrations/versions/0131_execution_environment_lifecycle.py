"""Durable exclusive environment fences and private batch snapshot metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0131_execution_environment"
down_revision = "0130_scope_model_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_execution_environments",
        sa.Column("environment_id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("target_key", sa.String(128), nullable=False, unique=True),
        sa.Column("inventory_hash", sa.String(71), nullable=False),
        sa.Column("max_snapshot_bytes", sa.Integer(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("active_lease_id", sa.String(128)),
        sa.CheckConstraint("generation BETWEEN 0 AND 9007199254740991"),
        sa.CheckConstraint("max_snapshot_bytes BETWEEN 1 AND 16777216"),
        sa.CheckConstraint("state IN ('available', 'leased', 'quarantined')"),
        sa.CheckConstraint("(state = 'available' AND active_lease_id IS NULL) OR "
                           "(state <> 'available' AND active_lease_id IS NOT NULL)"))
    op.create_table("quality_execution_environment_leases",
        sa.Column("lease_id", sa.String(128), primary_key=True),
        sa.Column("environment_id", sa.String(128), nullable=False),
        sa.Column("version_id", sa.String(128), nullable=False),
        sa.Column("batch_id", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("stopped_proof_id", sa.String(128)),
        sa.Column("baseline_verified", sa.Boolean(), nullable=False),
        sa.Column("baseline_proof_id", sa.String(128)),
        sa.Column("reset_verified", sa.Boolean(), nullable=False),
        sa.Column("reset_proof_id", sa.String(128)),
        sa.Column("quarantine_reason", sa.String(32)),
        sa.ForeignKeyConstraint(["environment_id"], ["quality_execution_environments.environment_id"]),
        sa.UniqueConstraint("environment_id", "generation"),
        sa.UniqueConstraint("lease_id", "generation"),
        sa.CheckConstraint("generation BETWEEN 1 AND 9007199254740991"),
        sa.CheckConstraint("expires_at > created_at AND expires_at <= created_at + interval '900 seconds'"),
        sa.CheckConstraint("phase IN ('leased', 'capturing_before', 'before_ready', 'running', 'stopping', 'stopped', "
                           "'capturing_after', 'after_ready', 'resetting', 'reset_complete', 'released', 'quarantined')"),
        sa.CheckConstraint("phase NOT IN ('before_ready', 'stopped', 'capturing_after', 'after_ready', 'resetting', 'reset_complete') "
                           "OR stopped_proof_id IS NOT NULL"),
        sa.CheckConstraint("NOT baseline_verified OR baseline_proof_id IS NOT NULL"),
        sa.CheckConstraint("phase IN ('leased', 'capturing_before', 'released', 'quarantined') OR baseline_verified"),
        sa.CheckConstraint("NOT reset_verified OR reset_proof_id IS NOT NULL"),
        sa.CheckConstraint("phase <> 'reset_complete' OR reset_verified"))
    op.create_index("uq_execution_environment_active_lease", "quality_execution_environment_leases",
                    ["environment_id"], unique=True, postgresql_where=sa.text("phase <> 'released'"))
    op.create_table("quality_execution_environment_snapshots",
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("lease_id", sa.String(128), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(8), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("encrypted_hash", sa.String(71), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_readback_verified", sa.Boolean(), nullable=False),
        sa.Column("snapshot_verified", sa.Boolean(), nullable=False),
        sa.Column("snapshot_proof_id", sa.String(128)),
        sa.Column("restore_verified", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("lease_id", "phase"),
        sa.UniqueConstraint("snapshot_id", "lease_id", "generation", "phase", "content_hash"),
        sa.ForeignKeyConstraint(["lease_id", "generation"],
            ["quality_execution_environment_leases.lease_id", "quality_execution_environment_leases.generation"]),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 16777216"),
        sa.CheckConstraint("phase IN ('before', 'after')"),
        sa.CheckConstraint("storage_readback_verified"),
        sa.CheckConstraint("NOT snapshot_verified OR snapshot_proof_id IS NOT NULL"),
        sa.CheckConstraint("NOT restore_verified"))
    op.execute("CREATE TRIGGER immutable_execution_environment_snapshots BEFORE UPDATE OR DELETE "
        "ON quality_execution_environment_snapshots FOR EACH ROW "
        "EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.create_table("quality_execution_snapshot_restores",
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("lease_id", sa.String(128), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(8), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("proof_id", sa.String(128), nullable=False, unique=True),
        sa.Column("independent_target_key", sa.String(128), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("independent_copy_verified", sa.Boolean(), nullable=False),
        sa.Column("source_unchanged", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id", "lease_id", "generation", "phase", "content_hash"],
            ["quality_execution_environment_snapshots." + key for key in
             ("snapshot_id", "lease_id", "generation", "phase", "content_hash")]),
        sa.CheckConstraint("verified AND independent_copy_verified AND source_unchanged"))
    op.execute("CREATE TRIGGER immutable_execution_snapshot_restores BEFORE UPDATE OR DELETE "
        "ON quality_execution_snapshot_restores FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.execute("""
        CREATE FUNCTION nasus_guard_environment_identity() RETURNS trigger AS $$
        BEGIN
          IF TG_TABLE_NAME = 'quality_execution_environments' THEN
            IF ROW(NEW.environment_id, NEW.project_id, NEW.target_key, NEW.inventory_hash, NEW.max_snapshot_bytes)
               IS DISTINCT FROM ROW(OLD.environment_id, OLD.project_id, OLD.target_key, OLD.inventory_hash, OLD.max_snapshot_bytes)
               OR NEW.generation < OLD.generation THEN
              RAISE EXCEPTION 'registered environment identity and fence cannot be rewritten';
            END IF;
          ELSE
            IF ROW(NEW.lease_id, NEW.environment_id, NEW.version_id, NEW.batch_id, NEW.owner_id,
                   NEW.generation, NEW.created_at, NEW.expires_at)
               IS DISTINCT FROM ROW(OLD.lease_id, OLD.environment_id, OLD.version_id, OLD.batch_id, OLD.owner_id,
                   OLD.generation, OLD.created_at, OLD.expires_at) THEN
              RAISE EXCEPTION 'lease identity and deadline cannot be rewritten';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("quality_execution_environments", "quality_execution_environment_leases"):
        op.execute(f"CREATE TRIGGER guard_{table} BEFORE UPDATE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_guard_environment_identity()")
        op.execute(f"CREATE TRIGGER retain_{table} BEFORE DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    tables = ("quality_execution_snapshot_restores", "quality_execution_environment_snapshots", "quality_execution_environment_leases",
              "quality_execution_environments")
    # Lock all tables before checking, so a concurrent registration cannot be lost.
    op.execute("LOCK TABLE " + ", ".join(tables) + " IN ACCESS EXCLUSIVE MODE")
    for table in tables:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("cannot discard retained execution environment lifecycle data")
    for table in tables:
        op.drop_table(table)
    op.execute("DROP FUNCTION nasus_guard_environment_identity()")
