from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class LinkDecisionRecord(Base):
    __tablename__ = "image_link_decisions"
    __table_args__ = (
        UniqueConstraint("assertion_id", "sequence"),
        UniqueConstraint("project_id", "assertion_id", "decision_id"),
        UniqueConstraint("previous_decision_id"),
        Index("uq_link_review_first", "assertion_id", unique=True, postgresql_where=text("previous_decision_id IS NULL")),
        ForeignKeyConstraint(["project_id", "proposal_id", "assertion_id"],
            ["image_reference_assertions.project_id", "image_reference_assertions.proposal_id", "image_reference_assertions.assertion_id"]),
        ForeignKeyConstraint(["project_id", "assertion_id", "previous_decision_id"],
            ["image_link_decisions.project_id", "image_link_decisions.assertion_id", "image_link_decisions.decision_id"]),
        CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_decision_id IS NULL) OR (sequence > 1 AND previous_decision_id IS NOT NULL))"),
    )
    decision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    proposal_id: Mapped[str]
    assertion_id: Mapped[str]
    previous_decision_id: Mapped[Optional[str]]
    sequence: Mapped[int]
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
