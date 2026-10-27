"""Pin compatibility knowledge objects to immutable code/source revisions."""
from alembic import op
import sqlalchemy as sa

revision = "0034_knowledge_code_reference"
down_revision = "0033_source_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing objects stay unpinned; deriving a pin from today's head is unsafe.
    op.add_column("knowledge_objects", sa.Column("code_reference", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_objects", "code_reference")
