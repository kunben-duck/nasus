"""Append-only reviewed test-design scopes; no legacy authority promotion."""
from alembic import op
import sqlalchemy as sa

revision = "0057_test_design_scope"
down_revision = "0056_context_retrieval_cancel"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_scope_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        *[sa.Column(k, sa.String(), nullable=False) for k in ("scope_id", "project_id", "context_id", "status",
            "invocation_id", "artifact_ref", "content_hash")],
        sa.Column("previous_revision_id", sa.String()), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("scope_id", "sequence"), sa.UniqueConstraint("project_id", "scope_id", "revision_id"),
        sa.UniqueConstraint("previous_revision_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["context_id"], ["system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "scope_id", "previous_revision_id"],
            ["quality_test_design_scope_revisions.project_id", "quality_test_design_scope_revisions.scope_id", "quality_test_design_scope_revisions.revision_id"]),
        sa.CheckConstraint("status IN ('approved', 'withdrawn')"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'approved') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"))
    op.create_index("ix_quality_test_design_scope_revisions_scope_id", "quality_test_design_scope_revisions", ["scope_id"])
    op.create_index("uq_test_design_scope_first", "quality_test_design_scope_revisions", ["scope_id"], unique=True,
        postgresql_where=sa.text("previous_revision_id IS NULL"))
    op.execute("CREATE TRIGGER immutable_quality_test_design_scope_revisions BEFORE UPDATE OR DELETE ON quality_test_design_scope_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_scope_revisions")):
        raise RuntimeError("cannot downgrade while reviewed test-design scopes exist")
    op.drop_table("quality_test_design_scope_revisions")
