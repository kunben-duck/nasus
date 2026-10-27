"""Immutable structural dispatch intent and PG-fenced activity ownership."""
from alembic import op
import sqlalchemy as sa

revision = "0082_structure_jobs"
down_revision = "0081_code_index_command"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_structure_jobs",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("user_identities.user_id"), nullable=False),
        sa.Column("command_hash", sa.String(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_image_structure_jobs_project_id", "image_structure_jobs", ["project_id"])
    op.execute("CREATE TRIGGER immutable_image_structure_jobs BEFORE UPDATE OR DELETE ON image_structure_jobs FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.create_table("image_structure_work_leases",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("image_structure_jobs.invocation_id"), primary_key=True),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("epoch >= 1", name="ck_structure_work_epoch"))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_structure_jobs)")):
        raise RuntimeError("Cannot remove populated structural dispatch history.")
    op.drop_table("image_structure_work_leases")
    op.drop_index("ix_image_structure_jobs_project_id", table_name="image_structure_jobs")
    op.drop_table("image_structure_jobs")
