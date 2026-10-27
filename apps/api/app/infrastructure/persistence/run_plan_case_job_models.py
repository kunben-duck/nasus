from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RunPlanCaseJobCancellationRecord(Base):
    __tablename__ = "quality_run_plan_case_job_cancellations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"), UniqueConstraint("control_id"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_run_plan_case_preparations.project_id", "quality_run_plan_case_preparations.invocation_id"]),
        ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    control_id: Mapped[str]
    actor_id: Mapped[str]
    command_digest: Mapped[str]
    preparation_digest: Mapped[str]
    control_digest: Mapped[str]
    recorded_at: Mapped[str]
    status: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanCaseJobCancellationDeliveryRecord(Base):
    __tablename__ = "quality_run_plan_case_job_cancel_deliveries"
    __table_args__ = (ForeignKeyConstraint(["project_id", "invocation_id"],
        ["quality_run_plan_case_job_cancellations.project_id", "quality_run_plan_case_job_cancellations.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    cancellation_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
