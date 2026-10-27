from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class GenerationJobCancellationRecord(Base):
    """Delivery receipt only; cancellation never refunds a native reservation."""
    __tablename__ = "quality_test_design_cancellations"
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class GenerationWorkLeaseRecord(Base):
    __tablename__ = "quality_test_design_work_leases"
    __table_args__ = (CheckConstraint("epoch >= 1"),)
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    owner_id: Mapped[str]
    epoch: Mapped[int]
    request_digest: Mapped[str]
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
