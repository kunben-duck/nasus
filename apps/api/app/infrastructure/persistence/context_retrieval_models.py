from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint, DateTime, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional

from .database import Base


class ContextRetrievalPlanRecord(Base):
    __tablename__ = "context_retrieval_plans"
    __table_args__ = (UniqueConstraint("project_id", "invocation_id"),
        ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_generations.project_id", "image_index_generations.generation_id"]),)
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    generation_id: Mapped[str]
    actor_id: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)


class ContextRetrievalCallRecord(Base):
    __tablename__ = "context_retrieval_calls"
    __table_args__ = (UniqueConstraint("project_id", "invocation_id", "ordinal"), CheckConstraint("ordinal BETWEEN 0 AND 7"),
        ForeignKeyConstraint(["project_id", "invocation_id"], ["context_retrieval_plans.project_id", "context_retrieval_plans.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    input_digest: Mapped[str]
    owner: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContextRetrievalBatchRecord(Base):
    __tablename__ = "context_retrieval_batches"
    __table_args__ = (ForeignKeyConstraint(["project_id", "invocation_id", "ordinal"],
        ["context_retrieval_calls.project_id", "context_retrieval_calls.invocation_id", "context_retrieval_calls.ordinal"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]


class ContextRetrievalResultRecord(Base):
    __tablename__ = "context_retrieval_results"
    __table_args__ = (ForeignKeyConstraint(["project_id", "invocation_id"],
        ["context_retrieval_plans.project_id", "context_retrieval_plans.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)


class ContextRetrievalCancellationRecord(Base):
    """Mutable delivery receipt, not a knowledge revision or a provider refund."""
    __tablename__ = "context_retrieval_cancellations"
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
