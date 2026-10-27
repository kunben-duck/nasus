"""Preserve unknown quality scores without rewriting historical measurements."""
from alembic import op
import sqlalchemy as sa

revision = "0097_unknown_quality_scores"
down_revision = "0096_materialization_inputs"
branch_labels = None
depends_on = None

PROFILE_COLUMNS = ("risk_score", "coverage_score", "release_score", "automation_feasibility", "confidence")


def upgrade():
    for column in PROFILE_COLUMNS:
        op.alter_column("quality_profiles", column, nullable=True, server_default=None)
    op.alter_column("task_contexts", "confidence", nullable=True, server_default=None)


def downgrade():
    conditions = " OR ".join(column + " IS NULL" for column in PROFILE_COLUMNS)
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_profiles WHERE " + conditions + ") "
            "OR EXISTS (SELECT 1 FROM task_contexts WHERE confidence IS NULL)")):
        raise RuntimeError("Cannot replace unknown quality assessments with invented scores.")
    for column in PROFILE_COLUMNS:
        op.alter_column("quality_profiles", column, nullable=False)
    op.alter_column("task_contexts", "confidence", nullable=False)
