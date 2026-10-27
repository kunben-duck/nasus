from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RunPlanBuildRecord(Base):
    __tablename__ = "quality_run_plan_build_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "image_revision_id", "manifest_id"),
        UniqueConstraint("project_id", "binding_id", "artifact_hash", "plan_digest", "image_revision_id", "manifest_id",
            name="uq_environment_build_parent"),
        UniqueConstraint("invocation_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "target_build_invocation_id"],
            ["quality_run_plan_build_members.project_id", "quality_run_plan_build_members.binding_id",
             "quality_run_plan_build_members.native_invocation_id"], name="fk_run_plan_build_target_member",
            use_alter=True, deferrable=True, initially="DEFERRED"),
        CheckConstraint("status = 'build_attested' AND code_source_count >= 1 AND code_source_count <= 1000"),
        Index("ix_run_plan_build_history", "project_id", "run_plan_id", "binding_id"),
    )
    binding_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    target_build_invocation_id: Mapped[str]
    target_artifact_hash: Mapped[str]
    code_source_count: Mapped[int]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    binding_digest: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanBuildMemberRecord(Base):
    __tablename__ = "quality_run_plan_build_members"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "native_invocation_id"),
        UniqueConstraint("project_id", "binding_id", "source_binding_id"),
        ForeignKeyConstraint(["project_id", "binding_id", "image_revision_id", "manifest_id"],
            ["quality_run_plan_build_bindings.project_id", "quality_run_plan_build_bindings.binding_id",
             "quality_run_plan_build_bindings.image_revision_id", "quality_run_plan_build_bindings.manifest_id"]),
        ForeignKeyConstraint(["project_id", "native_invocation_id", "build_id", "archive_hash", "receipt_digest"],
            ["quality_native_build_results.project_id", "quality_native_build_results.invocation_id",
             "quality_native_build_results.build_id", "quality_native_build_results.artifact_hash",
             "quality_native_build_results.receipt_digest"]),
        ForeignKeyConstraint(["project_id", "native_invocation_id", "build_id", "image_revision_id", "manifest_id", "source_binding_id", "source_revision_id"],
            ["quality_native_build_reservations.project_id", "quality_native_build_reservations.invocation_id",
             "quality_native_build_reservations.build_id", "quality_native_build_reservations.image_revision_id",
             "quality_native_build_reservations.manifest_id", "quality_native_build_reservations.binding_id",
             "quality_native_build_reservations.source_revision_id"]),
    )
    binding_id: Mapped[str] = mapped_column(primary_key=True)
    native_invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    source_binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    build_id: Mapped[str]
    archive_hash: Mapped[str]
    receipt_digest: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
