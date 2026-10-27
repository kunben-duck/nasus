"""Pin script model reservations to independent case admission; preserve old facts."""
from alembic import op
import sqlalchemy as sa


revision = "0122_automation_case_admission"
down_revision = "0121_case_approvals"
branch_labels = None
depends_on = None


def upgrade():
    table = "quality_automation_call_reservations"
    op.add_column(table, sa.Column("case_approval_revision_id", sa.String(), nullable=True))
    op.add_column(table, sa.Column("case_approval_artifact_hash", sa.String(), nullable=True))
    op.create_foreign_key("fk_automation_case_admission", table, "quality_case_approval_revisions",
        ["project_id", "generation_id", "case_approval_revision_id"], ["project_id", "generation_id", "revision_id"])
    op.create_check_constraint("ck_automation_case_admission_pair", table,
        "(case_approval_revision_id IS NULL) = (case_approval_artifact_hash IS NULL)")


def downgrade():
    table = "quality_automation_call_reservations"
    if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE case_approval_revision_id IS NOT NULL)")):
        raise RuntimeError("Cannot discard populated automation case admission provenance.")
    op.drop_constraint("ck_automation_case_admission_pair", table, type_="check")
    op.drop_constraint("fk_automation_case_admission", table, type_="foreignkey")
    op.drop_column(table, "case_approval_artifact_hash")
    op.drop_column(table, "case_approval_revision_id")
