"""Pin source-projected ACs and business rules to an exact requirement revision."""
from alembic import op
import sqlalchemy as sa

revision = "0046_requirement_components"
down_revision = "0045_image_review_membership"
branch_labels = None
depends_on = None

COMPONENT_PIN = "(kind IN ('acceptance_criterion', 'business_rule') AND parent_document_revision_id IS NOT NULL AND parent_document_revision_id <> document_revision_id) OR (kind NOT IN ('acceptance_criterion', 'business_rule') AND parent_document_revision_id IS NULL)"


def upgrade():
    op.add_column("source_document_revisions", sa.Column("parent_document_revision_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_source_document_parent", "source_document_revisions", "source_document_revisions",
        ["project_id", "binding_id", "source_revision_id", "parent_document_revision_id"],
        ["project_id", "binding_id", "source_revision_id", "document_revision_id"])
    op.create_check_constraint("ck_source_document_parent", "source_document_revisions", COMPONENT_PIN)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM source_document_revisions WHERE parent_document_revision_id IS NOT NULL")):
        raise RuntimeError("cannot downgrade while requirement component revisions exist")
    op.drop_constraint("ck_source_document_parent", "source_document_revisions", type_="check")
    op.drop_constraint("fk_source_document_parent", "source_document_revisions", type_="foreignkey")
    op.drop_column("source_document_revisions", "parent_document_revision_id")
