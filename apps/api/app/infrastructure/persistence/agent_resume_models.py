from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AgentResumeConsumptionRecord(Base):
    __tablename__ = "agent_resume_consumptions"
    goal_id: Mapped[str] = mapped_column(ForeignKey("agent_goals.id"), primary_key=True)
    checkpoint_digest: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str]
    project_id: Mapped[Optional[str]]
    workflow_id: Mapped[Optional[str]]
    transition_digest: Mapped[str]
    receipt_hash: Mapped[str]
