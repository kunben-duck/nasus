"""A confirmed command cannot replace its pinned source or provider on retry."""
from alembic import op
import sqlalchemy as sa


revision = "0081_code_index_command"
down_revision = "0080_code_index_protocol"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM code_index_generations
            GROUP BY invocation_id, binding_id HAVING count(*) > 1
        )
    """)):
        raise RuntimeError("Ambiguous code index command generations require independent historical review; no pins were rewritten.")
    op.create_unique_constraint("uq_code_index_command_binding", "code_index_generations", ["invocation_id", "binding_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM code_index_generations)")):
        raise RuntimeError("Cannot weaken populated code index command pins.")
    op.drop_constraint("uq_code_index_command_binding", "code_index_generations", type_="unique")
