from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BuildAuthorizationRecord(Base):
    __tablename__ = "image_build_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        UniqueConstraint("goal_id", "plan_id", name="uq_build_authorization_goal_plan"),
        UniqueConstraint("authorization_invocation_id"),
    )
    authorization_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    plan_id: Mapped[str]
    goal_id: Mapped[str] = mapped_column(ForeignKey("agent_goals.id"))
    authorization_invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class BuildWorkReservationRecord(Base):
    __tablename__ = "image_build_work_reservations"
    __table_args__ = (UniqueConstraint("authorization_id", "work_item_id"),)
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("image_build_authorizations.authorization_id"))
    work_item_id: Mapped[str]
