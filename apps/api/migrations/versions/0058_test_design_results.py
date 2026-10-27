"""Atomic immutable draft cases and planned coverage, never verified coverage."""
from alembic import op
import sqlalchemy as sa

revision = "0058_test_design_results"
down_revision = "0057_test_design_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_results",
        sa.Column("generation_id", sa.String(), primary_key=True),
        *[sa.Column(k, sa.String(), nullable=False) for k in ("project_id", "scope_revision_id", "invocation_id", "call_id",
            "status", "artifact_ref", "artifact_hash", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("invocation_id"), sa.UniqueConstraint("call_id"), sa.UniqueConstraint("project_id", "generation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["call_id"], ["llm_calls.id"]),
        sa.ForeignKeyConstraint(["scope_revision_id"], ["quality_test_design_scope_revisions.revision_id"]),
        sa.CheckConstraint("status = 'draft'"))
    for table, cases in (("quality_test_design_case_revisions", True), ("quality_test_design_coverage", False)):
        columns = [sa.Column("generation_id", sa.String(), primary_key=True)]
        if cases:
            columns.append(sa.Column("case_id", sa.String(), primary_key=True))
        op.create_table(table, *columns, sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]))
    for table in ("quality_test_design_results", "quality_test_design_case_revisions", "quality_test_design_coverage"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_results")):
        raise RuntimeError("cannot downgrade while test-design results exist")
    for table in ("quality_test_design_coverage", "quality_test_design_case_revisions", "quality_test_design_results"):
        op.drop_table(table)
