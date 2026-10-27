"""Immutable original materialization source inputs; no inferred legacy pins."""
from alembic import op
import sqlalchemy as sa

revision = "0096_materialization_inputs"
down_revision = "0095_source_acquisition_results"
branch_labels = None
depends_on = None


def upgrade():
    # Block concurrent command creation until the legacy roster and new schema
    # commit together; do not guess original inputs from today's source head.
    op.execute("LOCK TABLE tool_invocations IN SHARE MODE")
    op.add_column("tool_invocations", sa.Column("materialization_input_hash", sa.String(), nullable=True))
    op.create_table("materialization_legacy_commands",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True))
    op.execute("INSERT INTO materialization_legacy_commands (invocation_id) SELECT id FROM tool_invocations "
        "WHERE tool_id IN ('system_image.context.materialize', 'system_image.baseline.initialize')")
    op.execute("CREATE TRIGGER immutable_materialization_legacy_commands BEFORE UPDATE OR DELETE ON materialization_legacy_commands "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.create_table("materialization_source_inputs",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("user_identities.user_id"), nullable=False),
        sa.Column("command_hash", sa.String(), nullable=False),
        sa.Column("manifest_id", sa.String(), nullable=False),
        sa.Column("manifest_hash", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]))
    op.create_index("ix_materialization_source_inputs_project_id", "materialization_source_inputs", ["project_id"])
    op.execute("CREATE TRIGGER immutable_materialization_source_inputs BEFORE UPDATE OR DELETE ON materialization_source_inputs "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.execute("""CREATE FUNCTION nasus_reject_materialization_input_pin_change() RETURNS trigger AS $$
        BEGIN
            IF OLD.materialization_input_hash IS NOT NULL
                AND NEW.materialization_input_hash IS DISTINCT FROM OLD.materialization_input_hash THEN
                RAISE EXCEPTION 'materialization input pin is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER immutable_tool_materialization_input BEFORE UPDATE ON tool_invocations "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_materialization_input_pin_change()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM materialization_source_inputs)")):
        raise RuntimeError("Cannot discard populated materialization input history.")
    op.drop_table("materialization_source_inputs")
    op.drop_table("materialization_legacy_commands")
    op.execute("DROP TRIGGER immutable_tool_materialization_input ON tool_invocations")
    op.execute("DROP FUNCTION nasus_reject_materialization_input_pin_change()")
    op.drop_column("tool_invocations", "materialization_input_hash")
