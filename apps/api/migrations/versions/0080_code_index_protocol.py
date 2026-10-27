"""Immutable native protocol receipts; do not fabricate historical negotiation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0080_code_index_protocol"
down_revision = "0079_code_index_generations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("code_index_protocol_pins",
        sa.Column("generation_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("receipt", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "generation_id"],
            ["code_index_generations.project_id", "code_index_generations.generation_id"]))
    op.execute("CREATE TRIGGER immutable_code_index_protocol_pins BEFORE UPDATE OR DELETE ON code_index_protocol_pins "
               "FOR EACH ROW EXECUTE FUNCTION nasus_reject_code_index_pin_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM code_index_protocol_pins)")):
        raise RuntimeError("Cannot discard native code protocol receipts.")
    op.drop_table("code_index_protocol_pins")
