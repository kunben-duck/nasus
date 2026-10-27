from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceAcquisitionProgressRecord(Base):
    __tablename__ = "source_acquisition_progress"
    __table_args__ = (ForeignKeyConstraint(["project_id", "invocation_id"],
        ["source_acquisition_intents.project_id", "source_acquisition_intents.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    intent_hash: Mapped[str]
    result_pins: Mapped[list] = mapped_column(JSON)
    manifest_receipt_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    content_hash: Mapped[str]


class SourceAcquisitionResultRecord(Base):
    __tablename__ = "source_acquisition_results"
    __table_args__ = (
        ForeignKeyConstraint(["invocation_id"], ["source_acquisition_progress.invocation_id"]),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["source_acquisition_intents.project_id", "source_acquisition_intents.invocation_id"]),
        ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        CheckConstraint("status IN ('captured', 'legacy_unverified', 'failed')", name="ck_acquisition_result_status"),
        CheckConstraint("(status = 'captured') = (source_revision_id IS NOT NULL)", name="ck_acquisition_result_revision"),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    status: Mapped[str]
    source_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    inventory_id: Mapped[Optional[str]] = mapped_column(ForeignKey("source_acquisition_inventories.inventory_id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceAcquisitionManifestRecord(Base):
    __tablename__ = "source_acquisition_manifest_receipts"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["source_acquisition_intents.project_id", "source_acquisition_intents.invocation_id"]),
        ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    intent_hash: Mapped[str]
    results_hash: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    content_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
