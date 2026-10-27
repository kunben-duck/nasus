from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RunPlanObservationRecord(Base):
    __tablename__ = "quality_run_plan_observation_records"
    __table_args__ = (
        UniqueConstraint("project_id", "record_id"), UniqueConstraint("invocation_id"),
        UniqueConstraint("project_id", "run_plan_id", "run_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        CheckConstraint("status = 'recorded'"),
        CheckConstraint("case_count BETWEEN 1 AND 512 AND observed_case_count >= 0 AND outcome_unknown_case_count >= 0 "
            "AND no_result_case_count >= 0 AND case_count = observed_case_count + outcome_unknown_case_count + no_result_case_count "
            "AND passed_observation_count >= 0 AND failed_observation_count >= 0 "
            "AND passed_observation_count + failed_observation_count <= observed_case_count"),
    )
    record_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    invocation_id: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    collection_digest: Mapped[str]
    request_hash: Mapped[str]
    run_id: Mapped[str]
    status: Mapped[str]
    case_count: Mapped[int]
    observed_case_count: Mapped[int]
    outcome_unknown_case_count: Mapped[int]
    no_result_case_count: Mapped[int]
    passed_observation_count: Mapped[int]
    failed_observation_count: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanCaseObservationRecord(Base):
    __tablename__ = "quality_run_plan_case_observations"
    __table_args__ = (
        UniqueConstraint("record_id", "ordinal"),
        ForeignKeyConstraint(["project_id", "record_id"],
            ["quality_run_plan_observation_records.project_id", "quality_run_plan_observation_records.record_id"]),
        CheckConstraint("ordinal BETWEEN 0 AND 511"),
        CheckConstraint("status IN ('passed', 'failed', 'error', 'timed_out', 'not_executed', 'not_observed', 'outcome_unknown')"),
        CheckConstraint("(status = 'outcome_unknown' AND observation_digest IS NULL AND attempt_digest IS NOT NULL) "
            "OR (status IN ('not_executed', 'not_observed') AND observation_digest IS NULL AND attempt_digest IS NULL) "
            "OR (status IN ('passed', 'failed', 'error', 'timed_out') AND observation_digest IS NOT NULL AND attempt_digest IS NULL)"),
    )
    record_id: Mapped[str] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    ordinal: Mapped[int]
    case_digest: Mapped[str]
    status: Mapped[str]
    observation_digest: Mapped[Optional[str]] = mapped_column(nullable=True)
    attempt_digest: Mapped[Optional[str]] = mapped_column(nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
