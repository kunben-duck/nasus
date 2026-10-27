"""Persist source-pinned static structure and parser coverage observations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0037_code_analysis"
down_revision = "0036_source_inventories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_code_analyses",
        sa.Column("analysis_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("source_revision_id", sa.String(), nullable=False),
        sa.Column("report_hash", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.UniqueConstraint("source_revision_id", "report_hash"),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
    )
    op.execute("""
        CREATE FUNCTION nasus_reject_code_analysis_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'code analyses are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER immutable_source_code_analyses BEFORE UPDATE OR DELETE ON source_code_analyses
        FOR EACH ROW EXECUTE FUNCTION nasus_reject_code_analysis_mutation()
    """)


def downgrade() -> None:
    op.drop_table("source_code_analyses")
    op.execute("DROP FUNCTION nasus_reject_code_analysis_mutation()")
