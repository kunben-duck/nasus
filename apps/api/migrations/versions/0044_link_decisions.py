"""Append-only reviewer decisions bound to exact reference assertions."""
from alembic import op
import sqlalchemy as sa

revision = "0044_link_decisions"
down_revision = "0043_reference_links"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_reference_review_endpoint", "image_reference_assertions", ["project_id", "proposal_id", "assertion_id"])
    op.create_table("image_link_decisions", sa.Column("decision_id", sa.String(), primary_key=True),
        *[sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "proposal_id", "assertion_id", "content_hash")],
        sa.Column("previous_decision_id", sa.String(), nullable=True), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("assertion_id", "sequence"), sa.UniqueConstraint("previous_decision_id"),
        sa.UniqueConstraint("project_id", "assertion_id", "decision_id"),
        sa.ForeignKeyConstraint(["project_id", "proposal_id", "assertion_id"],
            ["image_reference_assertions.project_id", "image_reference_assertions.proposal_id", "image_reference_assertions.assertion_id"]),
        sa.ForeignKeyConstraint(["project_id", "assertion_id", "previous_decision_id"],
            ["image_link_decisions.project_id", "image_link_decisions.assertion_id", "image_link_decisions.decision_id"]),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_decision_id IS NULL) OR (sequence > 1 AND previous_decision_id IS NOT NULL))"))
    op.create_index("uq_link_review_first", "image_link_decisions", ["assertion_id"], unique=True,
        postgresql_where=sa.text("previous_decision_id IS NULL"))
    op.execute("CREATE TRIGGER immutable_image_link_decisions BEFORE UPDATE OR DELETE ON image_link_decisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_link_decisions")):
        raise RuntimeError("cannot downgrade while link decisions exist")
    op.drop_table("image_link_decisions")
    op.drop_constraint("uq_reference_review_endpoint", "image_reference_assertions", type_="unique")
