from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixturePreparationRecord(Base):
    __tablename__ = "quality_http_fixture_preparations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    request_digest: Mapped[str]
    actor_id: Mapped[str]
    confirmed_at: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class HttpFixturePreparationBindingRecord(Base):
    __tablename__ = "quality_http_fixture_preparation_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_preparations.project_id", "quality_http_fixture_preparations.invocation_id"]),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_commands.project_id", "quality_http_fixture_commands.invocation_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    preparation_digest: Mapped[str]
    intent_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
