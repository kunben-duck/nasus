from sqlalchemy import JSON, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureNativeGrantRecord(Base):
    __tablename__ = "quality_http_fixture_native_grants"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "grant_id"],
            ["quality_http_fixture_grants.project_id", "quality_http_fixture_grants.record_id"]),
        ForeignKeyConstraint(["project_id", "environment_record_id", "environment_record_artifact_hash", "inventory_hash", "operator_policy_digest"],
            ["quality_run_plan_environment_records.project_id", "quality_run_plan_environment_records.record_id",
             "quality_run_plan_environment_records.artifact_hash", "quality_run_plan_environment_records.inventory_hash",
             "quality_run_plan_environment_records.operator_policy_digest"]),
    )
    grant_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    grant_digest: Mapped[str]
    environment_record_id: Mapped[str]
    environment_record_artifact_hash: Mapped[str]
    inventory_hash: Mapped[str]
    operator_policy_digest: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
