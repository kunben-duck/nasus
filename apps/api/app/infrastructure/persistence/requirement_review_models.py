from sqlalchemy import ForeignKeyConstraint, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RequirementReviewEventRecord(Base):
    __tablename__ = "requirement_review_events"
    __table_args__ = (
        UniqueConstraint("invocation_id", "kind"),
        ForeignKeyConstraint(["project_id", "version_id", "us_id", "revision_id"],
            ["requirement_revisions.project_id", "requirement_revisions.version_id",
             "requirement_revisions.us_id", "requirement_revisions.revision_id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
    )
    event_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[str] = mapped_column(index=True)
    us_id: Mapped[str] = mapped_column(index=True)
    revision_id: Mapped[str] = mapped_column(index=True)
    invocation_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
