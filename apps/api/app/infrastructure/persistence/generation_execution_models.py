from sqlalchemy import Column, ForeignKeyConstraint, JSON, String, UniqueConstraint

from .database import Base


class GenerationCallReservationRecord(Base):
    __tablename__ = "quality_test_design_call_reservations"
    invocation_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    scope_revision_id = Column(String, nullable=False)
    call_id = Column(String, nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"), UniqueConstraint("invocation_id", "call_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["scope_revision_id"], ["quality_test_design_scope_revisions.revision_id"]),
    )


class GenerationNativeReplyRecord(Base):
    __tablename__ = "quality_test_design_native_replies"
    invocation_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    call_id = Column(String, nullable=False, unique=True)
    artifact_ref = Column(String, nullable=False)
    artifact_hash = Column(String, nullable=False)
    response_hash = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "invocation_id"], ["quality_test_design_call_reservations.project_id", "quality_test_design_call_reservations.invocation_id"]),
        ForeignKeyConstraint(["invocation_id", "call_id"], ["quality_test_design_call_reservations.invocation_id", "quality_test_design_call_reservations.call_id"]),
        ForeignKeyConstraint(["call_id"], ["llm_calls.id"]),
    )
