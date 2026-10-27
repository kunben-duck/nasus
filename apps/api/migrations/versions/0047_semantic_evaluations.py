"""Reserve confirmed one-shot model egress and archive proposed semantic evaluations."""
from alembic import op
import sqlalchemy as sa

revision = "0047_semantic_evaluations"
down_revision = "0046_requirement_components"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_semantic_call_reservations",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "image_revision_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("project_id", "invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]))
    op.create_table("image_semantic_evaluations", sa.Column("invocation_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "artifact_ref", "artifact_hash")],
        sa.ForeignKeyConstraint(["project_id", "invocation_id"], ["image_semantic_call_reservations.project_id", "image_semantic_call_reservations.invocation_id"]))
    for table in ("image_semantic_call_reservations", "image_semantic_evaluations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_semantic_call_reservations")):
        raise RuntimeError("cannot downgrade while model egress reservations exist")
    op.drop_table("image_semantic_evaluations")
    op.drop_table("image_semantic_call_reservations")
