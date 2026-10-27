from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureGrantRecord(Base):
    __tablename__ = "quality_http_fixture_grants"
    __table_args__ = (
        UniqueConstraint("project_id", "record_id"), UniqueConstraint("invocation_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "recipe_id", "recipe_artifact_hash"],
            ["quality_http_fixture_recipes.project_id", "quality_http_fixture_recipes.record_id", "quality_http_fixture_recipes.artifact_hash"]),
        CheckConstraint("operation IN ('setup', 'cleanup')"), CheckConstraint("status = 'issued'"),
        Index("ix_http_fixture_grant_attempt", "project_id", "attempt_id", "record_id"),
    )
    record_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    recipe_id: Mapped[str]
    recipe_artifact_hash: Mapped[str]
    attempt_id: Mapped[str]
    operation: Mapped[str]
    invocation_id: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    expires_at: Mapped[str]
    source_scope_digest: Mapped[str]
    scope_digest: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
