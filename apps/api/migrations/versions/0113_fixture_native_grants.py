"""Pin independent fixture consent to an original inventory, not a policy hash."""
from alembic import op
import sqlalchemy as sa

revision = "0113_fixture_native_grants"
down_revision = "0112_fixture_dispatch_consents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_fixture_native_environment_pin", "quality_run_plan_environment_records",
        ["project_id", "record_id", "artifact_hash", "inventory_hash", "operator_policy_digest"])
    op.create_table("quality_http_fixture_native_grants", sa.Column("grant_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "grant_digest",
            "environment_record_id", "environment_record_artifact_hash", "inventory_hash", "operator_policy_digest")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "grant_id"],
            ["quality_http_fixture_grants.project_id", "quality_http_fixture_grants.record_id"]),
        sa.ForeignKeyConstraint(["project_id", "environment_record_id", "environment_record_artifact_hash", "inventory_hash", "operator_policy_digest"],
            ["quality_run_plan_environment_records.project_id", "quality_run_plan_environment_records.record_id",
             "quality_run_plan_environment_records.artifact_hash", "quality_run_plan_environment_records.inventory_hash",
             "quality_run_plan_environment_records.operator_policy_digest"]))
    op.execute("CREATE TRIGGER immutable_quality_http_fixture_native_grants BEFORE UPDATE OR DELETE "
        "ON quality_http_fixture_native_grants FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM quality_http_fixture_native_grants)")):
        raise RuntimeError("Cannot discard populated original native fixture consent.")
    op.drop_table("quality_http_fixture_native_grants")
    op.drop_constraint("uq_fixture_native_environment_pin", "quality_run_plan_environment_records", type_="unique")
