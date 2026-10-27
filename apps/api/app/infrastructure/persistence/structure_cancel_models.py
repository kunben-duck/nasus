from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StructureCancellationRecord(Base):
    __tablename__ = "image_structure_cancellations"

    original_invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    cancellation_invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("user_identities.user_id"))
    command_hash: Mapped[str]
    request_payload: Mapped[dict] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
