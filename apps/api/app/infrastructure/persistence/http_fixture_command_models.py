"""Append-only command ancestry; ToolInvocation remains the lifecycle authority."""
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureCommandRecord(Base):
    __tablename__ = "quality_http_fixture_commands"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        UniqueConstraint("grant_id"),
        UniqueConstraint("work_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "grant_id"],
            ["quality_http_fixture_grants.project_id", "quality_http_fixture_grants.record_id"]),
        CheckConstraint("operation IN ('setup', 'cleanup')"),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    grant_id: Mapped[str]
    grant_digest: Mapped[str]
    request_digest: Mapped[str]
    actor_id: Mapped[str]
    operation: Mapped[str]
    scope_digest: Mapped[str]
    source_scope_digest: Mapped[str]
    work_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class HttpFixtureDispatchCommandRecord(Base):
    __tablename__ = "quality_http_fixture_dispatch_commands"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "claim_id"],
            ["quality_http_fixture_dispatches.project_id", "quality_http_fixture_dispatches.claim_id"]),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_commands.project_id", "quality_http_fixture_commands.invocation_id"]),
    )
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    invocation_id: Mapped[str]
    intent_digest: Mapped[str]
    request_digest: Mapped[str]
    dispatch_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
