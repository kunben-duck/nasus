from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class EnvironmentObservationRecord(Base):
    __tablename__ = "quality_run_plan_environment_records"
    __table_args__ = (
        UniqueConstraint("project_id", "record_id"), UniqueConstraint("invocation_id"),
        UniqueConstraint("project_id", "record_id", "artifact_hash", "inventory_hash", "operator_policy_digest",
            name="uq_fixture_native_environment_pin"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        ForeignKeyConstraint(["project_id", "build_binding_id", "build_binding_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plan_build_bindings.project_id", "quality_run_plan_build_bindings.binding_id",
             "quality_run_plan_build_bindings.artifact_hash", "quality_run_plan_build_bindings.plan_digest",
             "quality_run_plan_build_bindings.image_revision_id", "quality_run_plan_build_bindings.manifest_id"]),
        CheckConstraint("status = 'recorded'"),
        Index("ix_run_plan_environment_history", "project_id", "run_plan_id", "record_id"),
    )
    record_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    build_binding_id: Mapped[str]
    build_binding_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    environment_id: Mapped[str]
    operator_policy_digest: Mapped[str]
    target_artifact_hash: Mapped[str]
    inventory_hash: Mapped[str]
    observed_at: Mapped[str]
    invocation_id: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
