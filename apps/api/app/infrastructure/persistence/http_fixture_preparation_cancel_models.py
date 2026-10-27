"""Original preparation cancellation does not manufacture an execution intent."""
from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixturePreparationCancellationRecord(Base):
    __tablename__ = "quality_http_fixture_preparation_cancellations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"), UniqueConstraint("control_id"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_http_fixture_preparations.project_id", "quality_http_fixture_preparations.invocation_id"]),
        ForeignKeyConstraint(["control_id"], ["tool_invocations.id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    preparation_digest: Mapped[str]
    control_id: Mapped[str]
    control_digest: Mapped[str]
    request_digest: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class HttpFixturePreparationCancellationDeliveryRecord(Base):
    __tablename__ = "quality_http_fixture_preparation_cancel_deliveries"
    __table_args__ = (ForeignKeyConstraint(["project_id", "invocation_id"],
        ["quality_http_fixture_preparation_cancellations.project_id", "quality_http_fixture_preparation_cancellations.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    cancellation_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
