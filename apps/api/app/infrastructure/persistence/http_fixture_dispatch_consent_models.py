"""Immutable consent consumption of an original worker-owned fixture dispatch."""
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureDispatchConsentRecord(Base):
    __tablename__ = "quality_http_fixture_dispatch_consents"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatch_ownership.project_id", "quality_http_fixture_dispatch_ownership.claim_id"]),
        ForeignKeyConstraint(["project_id", "grant_id"],
            ["quality_http_fixture_grants.project_id", "quality_http_fixture_grants.record_id"]),
        CheckConstraint("operation IN ('setup', 'cleanup')"),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    grant_id: Mapped[str]
    grant_digest: Mapped[str]
    operation: Mapped[str]
    scope_digest: Mapped[str]
    source_scope_digest: Mapped[str]
    dispatch_digest: Mapped[str]
    recorded_at: Mapped[str]
    consumed_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
