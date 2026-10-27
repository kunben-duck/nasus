from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SemanticAssertionRecord(Base):
    __tablename__ = "image_semantic_assertions"
    __table_args__ = (
        UniqueConstraint("project_id", "claim_id", "assertion_id"),
        ForeignKeyConstraint(["project_id", "evaluation_id"], ["image_semantic_evaluations.project_id", "image_semantic_evaluations.invocation_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["image_revision_id", "subject_object_id"], ["image_object_members.image_revision_id", "image_object_members.object_id"]),
        ForeignKeyConstraint(["image_revision_id", "object_id"], ["image_object_members.image_revision_id", "image_object_members.object_id"]),
        CheckConstraint("predicate IN ('implements', 'asserts')"),
    )
    assertion_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    claim_id: Mapped[str] = mapped_column(index=True)
    evaluation_id: Mapped[str]
    image_revision_id: Mapped[str]
    subject_object_id: Mapped[str]
    object_id: Mapped[str]
    predicate: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class SemanticDecisionRecord(Base):
    __tablename__ = "image_semantic_decisions"
    __table_args__ = (
        UniqueConstraint("claim_id", "sequence"),
        UniqueConstraint("project_id", "claim_id", "decision_id"),
        UniqueConstraint("previous_decision_id"),
        Index("uq_semantic_review_first", "claim_id", unique=True, postgresql_where=text("previous_decision_id IS NULL")),
        ForeignKeyConstraint(["project_id", "claim_id", "assertion_id"], ["image_semantic_assertions.project_id", "image_semantic_assertions.claim_id", "image_semantic_assertions.assertion_id"]),
        ForeignKeyConstraint(["project_id", "claim_id", "previous_decision_id"], ["image_semantic_decisions.project_id", "image_semantic_decisions.claim_id", "image_semantic_decisions.decision_id"]),
        CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_decision_id IS NULL) OR (sequence > 1 AND previous_decision_id IS NOT NULL))"),
    )
    decision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    claim_id: Mapped[str]
    assertion_id: Mapped[str]
    previous_decision_id: Mapped[Optional[str]]
    sequence: Mapped[int]
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
