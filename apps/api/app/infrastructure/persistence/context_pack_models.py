from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ContextPackRecord(Base):
    __tablename__ = "system_image_context_packs"
    __table_args__ = (
        UniqueConstraint("invocation_id"),
        UniqueConstraint("project_id", "context_id", name="uq_context_project_pin"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    context_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    image_revision_id: Mapped[str]
    invocation_id: Mapped[str]
    request_hash: Mapped[str]
    content_hash: Mapped[str]
    artifact_ref: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
