from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class InvestigationRevisionRecord(Base):
    __tablename__ = "image_investigation_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        UniqueConstraint("project_id", "goal_id", "plan_id", "revision_number"),
        CheckConstraint("revision_number BETWEEN 1 AND 80"),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    plan_id: Mapped[str]
    goal_id: Mapped[str] = mapped_column(ForeignKey("agent_goals.id"))
    image_revision_id: Mapped[str] = mapped_column(ForeignKey("image_revisions.image_revision_id"))
    parent_revision_id: Mapped[Optional[str]] = mapped_column(ForeignKey("image_investigation_revisions.revision_id"))
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    revision_number: Mapped[int]
    revision_hash: Mapped[str]
    request_payload: Mapped[dict] = mapped_column(JSON)
    review_payload: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_identities.user_id"))
    created_at: Mapped[str]
