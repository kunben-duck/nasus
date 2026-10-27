"""Add explicit branch/tag identity without rewriting historical source pins."""
from alembic import op
import sqlalchemy as sa

revision = "0093_source_tracked_refs"
down_revision = "0092_build_tool_budget"
branch_labels = None
depends_on = None


def upgrade():
    for table, kind in (("source_bindings", "kind"), ("raw_assets", "source_type")):
        op.add_column(table, sa.Column("tracked_ref", sa.String(), nullable=True))
        op.create_check_constraint(f"ck_{table}_tracked_ref", table,
            f"tracked_ref IS NULL OR ({kind} = 'code' AND octet_length(tracked_ref) BETWEEN 11 AND 255 "
            "AND (tracked_ref LIKE 'refs/heads/%' OR tracked_ref LIKE 'refs/tags/%'))")
    op.execute("""CREATE FUNCTION nasus_preserve_source_binding_identity() RETURNS trigger AS $$
        BEGIN
            IF NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'source binding identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER preserve_source_binding_identity BEFORE UPDATE ON source_bindings "
        "FOR EACH ROW EXECUTE FUNCTION nasus_preserve_source_binding_identity()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM source_bindings WHERE tracked_ref IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM raw_assets WHERE tracked_ref IS NOT NULL)")):
        raise RuntimeError("Cannot discard populated tracked source identities.")
    op.execute("DROP TRIGGER preserve_source_binding_identity ON source_bindings")
    op.execute("DROP FUNCTION nasus_preserve_source_binding_identity()")
    for table in ("raw_assets", "source_bindings"):
        op.drop_constraint(f"ck_{table}_tracked_ref", table, type_="check")
        op.drop_column(table, "tracked_ref")
