from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BuildPlanRevisionRecord(Base):
    __tablename__ = "image_build_plan_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision_id"),
        UniqueConstraint("goal_id", "revision_number"),
        UniqueConstraint("parent_revision_id"),
        ForeignKeyConstraint(["project_id", "root_plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        ForeignKeyConstraint(["project_id", "from_plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        ForeignKeyConstraint(["project_id", "parent_revision_id"], ["image_build_plan_revisions.project_id", "image_build_plan_revisions.revision_id"]),
        CheckConstraint("revision_number BETWEEN 1 AND 80"),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("agent_goals.id"), index=True)
    root_plan_id: Mapped[str]
    from_plan_id: Mapped[str]
    plan_id: Mapped[str]
    parent_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    revision_number: Mapped[int]
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    revision_hash: Mapped[str]
