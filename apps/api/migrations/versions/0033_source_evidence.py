"""Register immutable source evidence and entity revision links."""

from alembic import op
import sqlalchemy as sa

revision = "0033_source_evidence"
down_revision = "0032_code_entity_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_evidence",
        sa.Column("evidence_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("source_revision_id", sa.String(), nullable=False),
        sa.Column("identity_hash", sa.String(), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("precision", sa.String(), nullable=False),
        sa.Column("file_hash", sa.String(), nullable=False),
        sa.Column("snippet_hash", sa.String(), nullable=True),
        sa.Column("object_ref", sa.String(), nullable=False),
        sa.Column("decoder_version", sa.String(), nullable=False),
        sa.Column("extractor_version", sa.String(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "binding_id", "source_revision_id", "evidence_id"),
        sa.UniqueConstraint("project_id", "binding_id", "source_revision_id", "identity_hash"),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
        sa.CheckConstraint("start_line >= 1 AND end_line >= start_line"),
        sa.CheckConstraint("precision IN ('exact', 'approximate')"),
        sa.CheckConstraint("(precision = 'exact') = (snippet_hash IS NOT NULL)"),
    )
    op.create_table(
        "code_entity_evidence",
        sa.Column("entity_revision_id", sa.String(), primary_key=True),
        sa.Column("evidence_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("binding_id", sa.String(), nullable=False),
        sa.Column("source_revision_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "entity_revision_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "evidence_id"],
            ["source_evidence.project_id", "source_evidence.binding_id", "source_evidence.source_revision_id", "source_evidence.evidence_id"],
        ),
    )
    op.execute("""
        CREATE FUNCTION nasus_reject_source_evidence_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'source evidence is append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("source_evidence", "code_entity_evidence"):
        op.execute(f"""
            CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION nasus_reject_source_evidence_mutation()
        """)


def downgrade() -> None:
    op.drop_table("code_entity_evidence")
    op.drop_table("source_evidence")
    op.execute("DROP FUNCTION nasus_reject_source_evidence_mutation()")
