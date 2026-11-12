from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RequirementRevisionRecord(Base):
    __tablename__ = "requirement_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_id", "us_id", "revision_id"),
        UniqueConstraint("us_id", "sequence"),
        CheckConstraint("sequence >= 1"),
        ForeignKeyConstraint(["project_id", "version_id"], ["versions.project_id", "versions.id"]),
        ForeignKeyConstraint(["us_id"], ["us_work_items.id"]),
        ForeignKeyConstraint(["project_id", "version_id", "us_id", "previous_revision_id"],
            ["requirement_revisions.project_id", "requirement_revisions.version_id",
             "requirement_revisions.us_id", "requirement_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[str] = mapped_column(index=True)
    us_id: Mapped[str] = mapped_column(index=True)
    sequence: Mapped[int]
    previous_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    image_revision_id: Mapped[str]
    invocation_id: Mapped[str] = mapped_column(unique=True)
    actor_id: Mapped[str]
    request_hash: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
