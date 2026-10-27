"""Append-only private dispatch history, not a canonical execution grant."""
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureDispatchRecord(Base):
    __tablename__ = "quality_http_fixture_dispatches"
    __table_args__ = (
        UniqueConstraint("project_id", "claim_id"),
        UniqueConstraint("project_id", "attempt_id", "case_id", "phase"),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        CheckConstraint("status = 'reserved'"),
        CheckConstraint("phase = 'setup' OR phase LIKE 'cleanup:%'"),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    attempt_id: Mapped[str]
    case_id: Mapped[str]
    phase: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    scope_digest: Mapped[str]
    command_digest: Mapped[str]
    request_hash: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    status: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class HttpFixtureResultRecord(Base):
    __tablename__ = "quality_http_fixture_results"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        CheckConstraint("status IN ('passed', 'failed', 'error', 'timed_out')"),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    status: Mapped[str]
    dispatch_digest: Mapped[str]
    receipt_digest: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
