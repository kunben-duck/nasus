"""Immutable raw acquisition inventories, including failed scans."""

from alembic import op
import sqlalchemy as sa

revision = "0036_source_inventories"
down_revision = "0035_source_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_acquisition_inventories",
        sa.Column("inventory_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("report_hash", sa.String(), nullable=False),
        sa.Column("report_ref", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("enumeration_complete", sa.Boolean(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.UniqueConstraint("binding_id", "report_hash"),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"],
        ),
        sa.CheckConstraint("status IN ('complete', 'failed')"),
        sa.CheckConstraint("file_count >= 0 AND byte_count >= 0 AND entry_count BETWEEN 1 AND 50000 AND file_count <= entry_count"),
        sa.CheckConstraint("status <> 'complete' OR (enumeration_complete AND file_count > 0)"),
    )
    op.execute("""
        CREATE FUNCTION nasus_reject_inventory_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'source inventories are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER immutable_source_acquisition_inventories
        BEFORE UPDATE OR DELETE ON source_acquisition_inventories
        FOR EACH ROW EXECUTE FUNCTION nasus_reject_inventory_mutation()
    """)


def downgrade() -> None:
    op.drop_table("source_acquisition_inventories")
    op.execute("DROP FUNCTION nasus_reject_inventory_mutation()")
