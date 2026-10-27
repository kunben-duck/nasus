"""Independent append-only structural cancellation, including pre-index queues."""
from alembic import op
import sqlalchemy as sa

revision = "0083_structure_cancellation"
down_revision = "0082_structure_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_structure_cancellations",
        sa.Column("original_invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("cancellation_invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("user_identities.user_id"), nullable=False),
        sa.Column("command_hash", sa.String(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_image_structure_cancellations_project_id", "image_structure_cancellations", ["project_id"])
    op.execute("CREATE TRIGGER immutable_image_structure_cancellations BEFORE UPDATE OR DELETE ON image_structure_cancellations FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_structure_cancellations)")):
        raise RuntimeError("Cannot remove populated structural cancellation history.")
    op.drop_index("ix_image_structure_cancellations_project_id", table_name="image_structure_cancellations")
    op.drop_table("image_structure_cancellations")
