from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AgentGoalStartReceiptRecord(Base):
    __tablename__ = "agent_goal_start_receipts"
    __table_args__ = (
        UniqueConstraint("goal_id"),
        ForeignKeyConstraint(["goal_id", "conversation_id", "workflow_id"],
            ["agent_goals.id", "agent_goals.conversation_id", "agent_goals.workflow_id"]),
        ForeignKeyConstraint(["conversation_id"], ["conversation_sessions.id"]),
        CheckConstraint("schema_version = 'nasus.agent-goal-start.v1'"),
    )
    workflow_id: Mapped[str] = mapped_column(primary_key=True)
    goal_id: Mapped[str]
    conversation_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    request_digest: Mapped[str]
    receipt_hash: Mapped[str]
    schema_version: Mapped[str]
