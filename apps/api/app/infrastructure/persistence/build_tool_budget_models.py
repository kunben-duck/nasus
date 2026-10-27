from sqlalchemy import CheckConstraint, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BuildToolBudgetRecord(Base):
    __tablename__ = "image_build_tool_budgets"
    goal_id: Mapped[str] = mapped_column(ForeignKey("agent_goals.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class BuildToolConsumptionRecord(Base):
    __tablename__ = "image_build_tool_consumptions"
    __table_args__ = (
        UniqueConstraint("goal_id", "sequence"),
        UniqueConstraint("goal_id", "work_key"),
        CheckConstraint("sequence BETWEEN 1 AND 1000"),
    )
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("image_build_tool_budgets.goal_id"), index=True)
    sequence: Mapped[int]
    work_key: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
