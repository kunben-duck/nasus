"""Append-only command-owned results and atomic manifest consumption receipts."""
from alembic import op
import sqlalchemy as sa

revision = "0095_source_acquisition_results"
down_revision = "0094_source_acquisition_intents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_source_acquisition_project_command", "source_acquisition_intents", ["project_id", "invocation_id"])
    op.create_table("source_acquisition_progress",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("intent_hash", sa.String(), nullable=False),
        sa.Column("result_pins", sa.JSON(), nullable=False),
        sa.Column("manifest_receipt_hash", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["source_acquisition_intents.project_id", "source_acquisition_intents.invocation_id"]))
    op.execute("""CREATE FUNCTION nasus_guard_source_acquisition_progress() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR ROW(OLD.invocation_id, OLD.project_id, OLD.intent_hash)
                IS DISTINCT FROM ROW(NEW.invocation_id, NEW.project_id, NEW.intent_hash) THEN
                RAISE EXCEPTION 'source acquisition progress identity is immutable';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER guarded_source_acquisition_progress BEFORE UPDATE OR DELETE ON source_acquisition_progress "
        "FOR EACH ROW EXECUTE FUNCTION nasus_guard_source_acquisition_progress()")
    op.create_table("source_acquisition_results",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_revision_id", sa.String(), nullable=True),
        sa.Column("inventory_id", sa.String(), sa.ForeignKey("source_acquisition_inventories.inventory_id"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["source_acquisition_intents.project_id", "source_acquisition_intents.invocation_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["source_acquisition_progress.invocation_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"], ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        sa.CheckConstraint("status IN ('captured', 'legacy_unverified', 'failed')", name="ck_acquisition_result_status"),
        sa.CheckConstraint("(status = 'captured') = (source_revision_id IS NOT NULL)", name="ck_acquisition_result_revision"))
    op.create_table("source_acquisition_manifest_receipts",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("intent_hash", sa.String(), nullable=False),
        sa.Column("results_hash", sa.String(), nullable=False),
        sa.Column("manifest_id", sa.String(), nullable=False),
        sa.Column("manifest_hash", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["source_acquisition_intents.project_id", "source_acquisition_intents.invocation_id"]),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]))
    for table in ("source_acquisition_results", "source_acquisition_manifest_receipts"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("source_acquisition_progress", "source_acquisition_results", "source_acquisition_manifest_receipts"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated acquisition result history.")
    op.drop_table("source_acquisition_manifest_receipts")
    op.drop_table("source_acquisition_results")
    op.drop_table("source_acquisition_progress")
    op.execute("DROP FUNCTION nasus_guard_source_acquisition_progress()")
    op.drop_constraint("uq_source_acquisition_project_command", "source_acquisition_intents", type_="unique")
