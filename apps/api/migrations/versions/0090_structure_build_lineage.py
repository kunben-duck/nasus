"""Capture actual code analysis lineage atomically; never infer legacy history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0090_structure_build_lineage"
down_revision = "0089_agent_active_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("image_structure_build_artifacts", sa.Column("lineage_required", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_table("image_structure_build_lineages",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("image_structure_build_artifacts.invocation_id"), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("image_revision_id", sa.String(), nullable=False),
        sa.Column("lineage_hash", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]))
    op.create_index("ix_image_structure_build_lineages_project_id", "image_structure_build_lineages", ["project_id"])
    op.execute("CREATE TRIGGER immutable_image_structure_build_lineages BEFORE UPDATE OR DELETE ON image_structure_build_lineages FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_structure_build_lineages) OR EXISTS (SELECT 1 FROM image_structure_build_artifacts WHERE lineage_required)")):
        raise RuntimeError("Cannot discard actual structural build lineage.")
    op.drop_table("image_structure_build_lineages")
    op.drop_column("image_structure_build_artifacts", "lineage_required")
