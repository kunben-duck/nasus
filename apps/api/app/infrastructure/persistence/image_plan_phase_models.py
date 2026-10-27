from typing import Optional
from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class ImagePlanPhaseRecord(Base):
    __tablename__ = "agent_image_plan_phases"
    __table_args__ = (
        UniqueConstraint("project_id", "phase_id"), UniqueConstraint("goal_id", "phase_number"),
        UniqueConstraint("goal_id", "revision_id"), UniqueConstraint("parent_phase_id"),
        CheckConstraint("phase_number BETWEEN 1 AND 80"),
        ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        ForeignKeyConstraint(["project_id", "revision_id"], ["image_build_plan_revisions.project_id", "image_build_plan_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "parent_phase_id"], ["agent_image_plan_phases.project_id", "agent_image_plan_phases.phase_id"]),
    )
    phase_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("agent_goals.id"), index=True)
    revision_id: Mapped[str]
    plan_id: Mapped[str]
    parent_phase_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    phase_number: Mapped[int]
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    phase_hash: Mapped[str]
