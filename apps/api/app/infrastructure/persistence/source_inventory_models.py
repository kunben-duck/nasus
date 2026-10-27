from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceInventoryRecord(Base):
    __tablename__ = "source_acquisition_inventories"
    __table_args__ = (
        UniqueConstraint("binding_id", "report_hash"),
        ForeignKeyConstraint(
            ["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"],
        ),
        CheckConstraint("status IN ('complete', 'failed')"),
        CheckConstraint("file_count >= 0 AND byte_count >= 0 AND entry_count BETWEEN 1 AND 50000 AND file_count <= entry_count"),
        CheckConstraint("status <> 'complete' OR (enumeration_complete AND file_count > 0)"),
    )

    inventory_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_id: Mapped[str]
    report_hash: Mapped[str]
    report_ref: Mapped[str]
    status: Mapped[str]
    enumeration_complete: Mapped[bool]
    file_count: Mapped[int]
    byte_count: Mapped[int]
    entry_count: Mapped[int]
    recorded_at: Mapped[str]
