from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ReferenceProposalRecord(Base):
    __tablename__ = "image_reference_proposals"
    __table_args__ = (
        UniqueConstraint("project_id", "proposal_id"),
        UniqueConstraint("project_id", "proposal_id", "image_revision_id"),
        UniqueConstraint("project_id", "content_hash"),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    proposal_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    content_hash: Mapped[str]
    method_version: Mapped[str]
    document_count: Mapped[int]
    gaps: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str]
    created_by: Mapped[str]


class ReferenceAssertionRecord(Base):
    __tablename__ = "image_reference_assertions"
    __table_args__ = (
        UniqueConstraint("project_id", "proposal_id", "assertion_id", name="uq_reference_review_endpoint"),
        UniqueConstraint("proposal_id", "ordinal"),
        ForeignKeyConstraint(["project_id", "proposal_id", "image_revision_id"], ["image_reference_proposals.project_id", "image_reference_proposals.proposal_id", "image_reference_proposals.image_revision_id"]),
        ForeignKeyConstraint(["image_revision_id", "subject_object_id", "subject_revision_id"], ["image_object_members.image_revision_id", "image_object_members.object_id", "image_object_members.document_revision_id"]),
        ForeignKeyConstraint(["image_revision_id", "object_id", "object_revision_id"], ["image_object_members.image_revision_id", "image_object_members.object_id", "image_object_members.document_revision_id"]),
        CheckConstraint("predicate = 'references' AND semantic_kind = 'observed' AND status = 'proposed'"),
    )
    assertion_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    proposal_id: Mapped[str]
    image_revision_id: Mapped[str]
    ordinal: Mapped[int]
    subject_object_id: Mapped[str]
    subject_revision_id: Mapped[str]
    object_id: Mapped[str]
    object_revision_id: Mapped[str]
    reference_id: Mapped[str]
    subject_evidence_ids: Mapped[list] = mapped_column(JSON)
    object_evidence_ids: Mapped[list] = mapped_column(JSON)
    predicate: Mapped[str]
    semantic_kind: Mapped[str]
    status: Mapped[str]
    applicability: Mapped[str]


class ReferenceProposalInvocationRecord(Base):
    __tablename__ = "image_reference_proposal_invocations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "proposal_id"], ["image_reference_proposals.project_id", "image_reference_proposals.proposal_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    proposal_id: Mapped[str]
