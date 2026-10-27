from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ImagePublicationReviewRecord(Base):
    __tablename__ = "image_publication_reviews"
    __table_args__ = (
        UniqueConstraint("project_id", "review_id"), UniqueConstraint("claim_digest", "sequence"),
        UniqueConstraint("invocation_id"),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id"], ["baselines.project_id", "baselines.id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "rollback_publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"], name="fk_publication_review_rollback"),
        CheckConstraint("sequence > 0"),
    )
    review_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    baseline_id: Mapped[str]
    image_revision_id: Mapped[str]
    claim_digest: Mapped[str] = mapped_column(index=True)
    sequence: Mapped[int]
    invocation_id: Mapped[str]
    request_hash: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    rollback_publication_id: Mapped[Optional[str]] = mapped_column(nullable=True)


class ImagePublicationRecord(Base):
    __tablename__ = "image_publications"
    __table_args__ = (
        UniqueConstraint("project_id", "baseline_id", "publication_id"),
        UniqueConstraint("project_id", "baseline_id", "sequence"), UniqueConstraint("invocation_id"),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id"], ["baselines.project_id", "baselines.id"]),
        ForeignKeyConstraint(["project_id", "approval_id"], ["image_publication_reviews.project_id", "image_publication_reviews.review_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "previous_publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "rollback_publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"], name="fk_publication_rollback"),
        CheckConstraint("(sequence = 1 AND previous_publication_id IS NULL) OR (sequence > 1 AND previous_publication_id IS NOT NULL)"),
    )
    publication_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    baseline_id: Mapped[str]
    image_revision_id: Mapped[str]
    approval_id: Mapped[str]
    previous_publication_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    sequence: Mapped[int]
    invocation_id: Mapped[str]
    request_hash: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    rollback_publication_id: Mapped[Optional[str]] = mapped_column(nullable=True)


class ImagePublicationHeadRecord(Base):
    __tablename__ = "image_publication_heads"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        CheckConstraint("sequence > 0"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    baseline_id: Mapped[str] = mapped_column(primary_key=True)
    publication_id: Mapped[str]
    sequence: Mapped[int]
