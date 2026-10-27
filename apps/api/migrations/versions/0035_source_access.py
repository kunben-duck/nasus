"""Append-only source policies and atomic project ACL epochs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035_source_access"
down_revision = "0034_knowledge_code_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_access_epochs",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("acl_epoch", sa.Integer(), nullable=False),
        sa.CheckConstraint("acl_epoch >= 0"),
    )
    op.create_table(
        "source_access_policy_revisions",
        sa.Column("policy_revision_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("acl_epoch", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("reader_user_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=False),
        sa.Column("invocation_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "policy_revision_id"),
        sa.UniqueConstraint("project_id", "acl_epoch"),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"],
        ),
        sa.CheckConstraint("acl_epoch > 0"),
        sa.CheckConstraint("visibility IN ('project', 'restricted')"),
        sa.CheckConstraint("cardinality(reader_user_ids) <= 128"),
        sa.CheckConstraint("visibility = 'restricted' OR cardinality(reader_user_ids) = 0"),
    )
    op.create_table(
        "source_access_policy_heads",
        sa.Column("binding_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("policy_revision_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "policy_revision_id"],
            ["source_access_policy_revisions.project_id", "source_access_policy_revisions.binding_id",
             "source_access_policy_revisions.policy_revision_id"],
        ),
    )
    op.execute("""
        CREATE FUNCTION nasus_reject_source_access_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'source access policies are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER immutable_source_access_policy_revisions
        BEFORE UPDATE OR DELETE ON source_access_policy_revisions
        FOR EACH ROW EXECUTE FUNCTION nasus_reject_source_access_mutation()
    """)
    op.execute("""
        CREATE FUNCTION nasus_check_source_access_epoch() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'source access epoch cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF NEW.project_id <> OLD.project_id OR NEW.acl_epoch <> OLD.acl_epoch + 1 THEN
                RAISE EXCEPTION 'source access epoch must advance by one' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER monotonic_source_access_epoch BEFORE UPDATE OR DELETE ON source_access_epochs
        FOR EACH ROW EXECUTE FUNCTION nasus_check_source_access_epoch()
    """)


def downgrade() -> None:
    op.drop_table("source_access_policy_heads")
    op.drop_table("source_access_policy_revisions")
    op.drop_table("source_access_epochs")
    op.execute("DROP FUNCTION nasus_reject_source_access_mutation()")
    op.execute("DROP FUNCTION nasus_check_source_access_epoch()")
