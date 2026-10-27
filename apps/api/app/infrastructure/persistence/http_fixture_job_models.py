from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureCancellationRecord(Base):
    __tablename__ = "quality_http_fixture_cancellations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"), UniqueConstraint("control_id"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_commands.project_id", "quality_http_fixture_commands.invocation_id"]),
        ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    control_id: Mapped[str]
    control_digest: Mapped[str]
    request_digest: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class HttpFixtureCancellationDeliveryRecord(Base):
    __tablename__ = "quality_http_fixture_cancellation_deliveries"
    __table_args__ = (ForeignKeyConstraint(["project_id", "invocation_id"],
        ["quality_http_fixture_cancellations.project_id", "quality_http_fixture_cancellations.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    cancellation_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
