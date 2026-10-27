"""Mutable private worker lease plus immutable ownership of original dispatches."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureWorkLeaseRecord(Base):
    __tablename__ = "quality_http_fixture_work_leases"
    __table_args__ = (
        UniqueConstraint("project_id", "work_id"),
        UniqueConstraint("project_id", "attempt_id", "case_id", "operation"),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        CheckConstraint("operation IN ('setup', 'cleanup') AND epoch >= 1"),
        CheckConstraint("acquired_at <= renewed_at AND renewed_at < expires_at"),
    )
    work_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    attempt_id: Mapped[str]
    case_id: Mapped[str]
    operation: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    scope: Mapped[dict] = mapped_column(JSON)
    scope_digest: Mapped[str]
    request_digest: Mapped[str]
    actor_id: Mapped[str]
    owner_id: Mapped[str]
    epoch: Mapped[int]
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HttpFixtureDispatchOwnershipRecord(Base):
    __tablename__ = "quality_http_fixture_dispatch_ownership"
    __table_args__ = (
        UniqueConstraint("project_id", "claim_id", name="uq_fixture_ownership_project_claim"),
        ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_http_fixture_work_leases.project_id", "quality_http_fixture_work_leases.work_id"]),
        CheckConstraint("epoch >= 1"),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    work_id: Mapped[str]
    owner_id: Mapped[str]
    epoch: Mapped[int]
    request_digest: Mapped[str]
    dispatch_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
