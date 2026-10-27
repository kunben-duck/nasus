from sqlalchemy import CheckConstraint, ForeignKeyConstraint, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ContextInvalidationRecord(Base):
    __tablename__ = "system_image_context_invalidations"
    __table_args__ = (
        UniqueConstraint("invocation_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        *[ForeignKeyConstraint(["project_id", "binding_id", key],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"])
            for key in ("before_revision_id", "after_revision_id")],
    )
    invalidation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    context_id: Mapped[str] = mapped_column(index=True)
    binding_id: Mapped[str]
    before_revision_id: Mapped[str]
    after_revision_id: Mapped[str]
    invocation_id: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)


class ContextInvalidationNodeRecord(Base):
    __tablename__ = "system_image_context_invalidation_nodes"
    __table_args__ = (
        ForeignKeyConstraint(["invalidation_id"], ["system_image_context_invalidations.invalidation_id"]),
        CheckConstraint("kind IN ('context', 'scope', 'generation', 'case', 'coverage', 'mapping')"),
    )
    invalidation_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    artifact_id: Mapped[str]
    artifact_hash: Mapped[str]


class ContextInvalidationEdgeRecord(Base):
    __tablename__ = "system_image_context_invalidation_edges"
    __table_args__ = tuple(ForeignKeyConstraint(["invalidation_id", key],
        ["system_image_context_invalidation_nodes.invalidation_id", "system_image_context_invalidation_nodes.node_key"])
        for key in ("node_key", "parent_key"))
    invalidation_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    parent_key: Mapped[str] = mapped_column(primary_key=True)
