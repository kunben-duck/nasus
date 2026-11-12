"""Allow full Git commit selectors without rewriting source identity."""
from alembic import op
import sqlalchemy as sa


revision = "0123_fixed_git_commit"
down_revision = "0122_automation_case_admission"
branch_labels = None
depends_on = None

_TABLES = (("source_bindings", "kind"), ("raw_assets", "source_type"))
_SYMBOLIC_REF = ("octet_length(tracked_ref) BETWEEN 11 AND 255 "
    "AND (tracked_ref LIKE 'refs/heads/%' OR tracked_ref LIKE 'refs/tags/%')")
_FIXED_COMMIT = """octet_length(tracked_ref) = 40 AND tracked_ref COLLATE "C" ~ '^[0-9a-f]{40}$'"""


def _replace_constraints(*, allow_fixed):
    selectors = f"({_SYMBOLIC_REF}) OR ({_FIXED_COMMIT})" if allow_fixed else _SYMBOLIC_REF
    for table, kind in _TABLES:
        name = f"ck_{table}_tracked_ref"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"tracked_ref IS NULL OR ({kind} = 'code' AND ({selectors}))")


def upgrade():
    _replace_constraints(allow_fixed=True)


def downgrade():
    bind = op.get_bind()
    for table, _ in _TABLES:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {_FIXED_COMMIT})")):
            raise RuntimeError("Cannot discard populated fixed Git commit identities.")
    _replace_constraints(allow_fixed=False)
