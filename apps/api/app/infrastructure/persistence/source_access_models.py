from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceAccessEpochRecord(Base):
    __tablename__ = "source_access_epochs"
    __table_args__ = (CheckConstraint("acl_epoch >= 0"),)

    project_id: Mapped[str] = mapped_column(primary_key=True)
    acl_epoch: Mapped[int]


class SourceAccessPolicyRevisionRecord(Base):
    __tablename__ = "source_access_policy_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "policy_revision_id"),
        UniqueConstraint("project_id", "acl_epoch"),
        ForeignKeyConstraint(
            ["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"],
        ),
        CheckConstraint("acl_epoch > 0"),
        CheckConstraint("visibility IN ('project', 'restricted')"),
        CheckConstraint("cardinality(reader_user_ids) <= 128"),
        CheckConstraint("visibility = 'restricted' OR cardinality(reader_user_ids) = 0"),
    )

    policy_revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    acl_epoch: Mapped[int]
    visibility: Mapped[str]
    reader_user_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    changed_by: Mapped[str]
    invocation_id: Mapped[str]
    created_at: Mapped[str]


class SourceAccessPolicyHeadRecord(Base):
    __tablename__ = "source_access_policy_heads"
    __table_args__ = (ForeignKeyConstraint(
        ["project_id", "binding_id", "policy_revision_id"],
        ["source_access_policy_revisions.project_id", "source_access_policy_revisions.binding_id",
         "source_access_policy_revisions.policy_revision_id"],
    ),)

    binding_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    policy_revision_id: Mapped[str]
