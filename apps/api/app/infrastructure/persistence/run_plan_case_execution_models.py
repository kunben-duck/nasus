"""Independent case work: immutable inputs/claims/results, mutable PG ownership."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RunPlanCaseWorkRecord(Base):
    __tablename__ = "quality_run_plan_case_work"
    __table_args__ = (
        UniqueConstraint("project_id", "work_id"), UniqueConstraint("project_id", "run_id"),
        UniqueConstraint("invocation_id"), ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
    )
    work_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_id: Mapped[str]
    invocation_id: Mapped[str]
    actor_id: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    scope_digest: Mapped[str]
    roster_digest: Mapped[str]
    recorded_at: Mapped[str]
    scope: Mapped[dict] = mapped_column(JSON)
    roster: Mapped[list] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanCaseLeaseRecord(Base):
    __tablename__ = "quality_run_plan_case_leases"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_run_plan_case_work.project_id", "quality_run_plan_case_work.work_id"]),
        CheckConstraint("epoch >= 1 AND acquired_at <= renewed_at AND renewed_at < expires_at"),
        CheckConstraint("expires_at = renewed_at + INTERVAL '90 seconds'"),
    )
    work_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    owner_id: Mapped[str]
    epoch: Mapped[int]
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunPlanCaseClaimRecord(Base):
    __tablename__ = "quality_run_plan_case_claims"
    __table_args__ = (
        UniqueConstraint("project_id", "claim_id"), UniqueConstraint("work_id", "case_id"),
        UniqueConstraint("work_id", "ordinal"),
        ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_run_plan_case_work.project_id", "quality_run_plan_case_work.work_id"]),
        CheckConstraint("ordinal >= 0 AND ordinal < 512 AND epoch >= 1"),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    work_id: Mapped[str]
    case_id: Mapped[str]
    ordinal: Mapped[int]
    owner_id: Mapped[str]
    epoch: Mapped[int]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanCaseOutcomeRecord(Base):
    __tablename__ = "quality_run_plan_case_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_run_plan_case_claims.project_id", "quality_run_plan_case_claims.claim_id"]),
        CheckConstraint("status IN ('passed', 'failed', 'error', 'timed_out')"),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    status: Mapped[str]
    recorded_at: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    observation_digest: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanCaseCancellationRecord(Base):
    __tablename__ = "quality_run_plan_case_cancellations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_run_plan_case_work.project_id", "quality_run_plan_case_work.work_id"]),
        ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]), UniqueConstraint("control_id"),
    )
    work_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    control_id: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
