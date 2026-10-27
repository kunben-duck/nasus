from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RunPlanCasePreparationRecord(Base):
    __tablename__ = "quality_run_plan_case_preparations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        UniqueConstraint("project_id", "run_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_id: Mapped[str]
    selection_digest: Mapped[str]
    command_digest: Mapped[str]
    actor_id: Mapped[str]
    confirmed_at: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class RunPlanCasePreparationBindingRecord(Base):
    __tablename__ = "quality_run_plan_case_preparation_bindings"
    __table_args__ = (
        UniqueConstraint("work_id"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_run_plan_case_preparations.project_id", "quality_run_plan_case_preparations.invocation_id"]),
        ForeignKeyConstraint(["project_id", "work_id"],
            ["quality_run_plan_case_work.project_id", "quality_run_plan_case_work.work_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_id: Mapped[str]
    work_id: Mapped[str]
    preparation_digest: Mapped[str]
    work_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
