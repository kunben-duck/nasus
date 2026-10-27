from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class CodeAnalysisRecord(Base):
    __tablename__ = "source_code_analyses"
    __table_args__ = (
        UniqueConstraint("source_revision_id", "report_hash"),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
    )

    analysis_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    report_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
    recorded_at: Mapped[str]
