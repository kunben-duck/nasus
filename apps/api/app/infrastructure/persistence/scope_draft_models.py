from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ScopeDraftEventRecord(Base):
    __tablename__ = "quality_scope_draft_events"
    __table_args__ = (
        UniqueConstraint("invocation_id", "kind"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        CheckConstraint("kind IN ('reserved', 'replied', 'failed', 'draft')"),
    )
    event_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    context_id: Mapped[str]
    invocation_id: Mapped[str]
    kind: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
