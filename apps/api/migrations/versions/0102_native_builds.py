"""Canonical native build reservations and original outputs, never target execution."""
from alembic import op
import sqlalchemy as sa

revision = "0102_native_builds"
down_revision = "0101_run_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_native_build_reservations",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "build_id", "image_revision_id", "manifest_id", "binding_id", "source_revision_id",
            "actor_id", "worker_owner", "request_hash", "recorded_at", "content_hash")),
        sa.Column("worker_epoch", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id", "build_id"), sa.UniqueConstraint("build_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        sa.ForeignKeyConstraint(["project_id", "manifest_id", "binding_id", "source_revision_id"],
            ["source_manifest_members.project_id", "source_manifest_members.manifest_id",
             "source_manifest_members.binding_id", "source_manifest_members.source_revision_id"]),
        sa.CheckConstraint("worker_epoch >= 1"))
    op.create_table("quality_native_build_results",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "project_id", "build_id", "artifact_ref", "artifact_hash", "receipt_digest", "recorded_at", "content_hash")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "invocation_id"), sa.UniqueConstraint("build_id"),
        sa.ForeignKeyConstraint(["project_id", "invocation_id", "build_id"],
            ["quality_native_build_reservations.project_id", "quality_native_build_reservations.invocation_id",
             "quality_native_build_reservations.build_id"]))
    for table in ("quality_native_build_reservations", "quality_native_build_results"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.create_table("quality_native_build_work_leases",
        sa.Column("invocation_id", sa.String(), primary_key=True),
        *(sa.Column(name, sa.String(), nullable=False) for name in ("project_id", "owner_id", "request_digest")),
        sa.Column("epoch", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.DateTime(timezone=True), nullable=False) for name in ("acquired_at", "renewed_at", "expires_at")),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]), sa.CheckConstraint("epoch >= 1"))
    op.create_table("quality_native_build_cancellations",
        sa.Column("invocation_id", sa.String(), primary_key=True), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))


def downgrade():
    for table in ("quality_native_build_results", "quality_native_build_reservations", "quality_native_build_cancellations",
                  "quality_native_build_work_leases"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot discard populated native build history or worker state.")
    for table in ("quality_native_build_cancellations", "quality_native_build_work_leases",
                  "quality_native_build_results", "quality_native_build_reservations"):
        op.drop_table(table)
