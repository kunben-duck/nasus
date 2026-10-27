from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StructureJobRecord(Base):
    __tablename__ = "image_structure_jobs"

    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("user_identities.user_id"))
    command_hash: Mapped[str]
    request_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StructureWorkLeaseRecord(Base):
    __tablename__ = "image_structure_work_leases"
    __table_args__ = (CheckConstraint("epoch >= 1", name="ck_structure_work_epoch"),)

    invocation_id: Mapped[str] = mapped_column(ForeignKey("image_structure_jobs.invocation_id"), primary_key=True)
    owner_id: Mapped[str]
    epoch: Mapped[int]
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
