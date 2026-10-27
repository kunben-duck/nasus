"""Fixed reviewed-case native script drafts, never executable approval."""
from alembic import op
import sqlalchemy as sa

revision = "0098_automation_script_drafts"
down_revision = "0097_unknown_quality_scores"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_automation_call_reservations",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("generation_id", sa.String(), nullable=False), sa.Column("mapping_revision_id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("invocation_id", "call_id"),
        sa.ForeignKeyConstraint(["project_id", "generation_id", "mapping_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id",
             "quality_test_design_mapping_revisions.revision_id"]))
    op.create_table("quality_automation_native_replies",
        sa.Column("invocation_id", sa.String(), primary_key=True), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), sa.ForeignKey("llm_calls.id"), nullable=False, unique=True),
        sa.Column("artifact_ref", sa.String(), nullable=False), sa.Column("artifact_hash", sa.String(), nullable=False),
        sa.Column("response_hash", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False), sa.UniqueConstraint("project_id", "invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_automation_call_reservations.project_id", "quality_automation_call_reservations.invocation_id"]),
        sa.ForeignKeyConstraint(["invocation_id", "call_id"],
            ["quality_automation_call_reservations.invocation_id", "quality_automation_call_reservations.call_id"]))
    op.create_table("quality_automation_script_revisions",
        sa.Column("script_revision_id", sa.String(), primary_key=True), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("invocation_id", sa.String(), nullable=False, unique=True), sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("artifact_ref", sa.String(), nullable=False), sa.Column("artifact_hash", sa.String(), nullable=False),
        sa.Column("response_hash", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "script_revision_id"), sa.CheckConstraint("status = 'draft'"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_automation_native_replies.project_id", "quality_automation_native_replies.invocation_id"]),
        sa.ForeignKeyConstraint(["invocation_id", "call_id"],
            ["quality_automation_call_reservations.invocation_id", "quality_automation_call_reservations.call_id"]))
    for table in ("quality_automation_call_reservations", "quality_automation_native_replies", "quality_automation_script_revisions"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    for table in ("quality_automation_script_revisions", "quality_automation_native_replies", "quality_automation_call_reservations"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated automation call or script history.")
    for table in ("quality_automation_script_revisions", "quality_automation_native_replies", "quality_automation_call_reservations"):
        op.drop_table(table)
