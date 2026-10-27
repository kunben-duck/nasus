from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint

from .database import Base


class GenerationBatchReservationRecord(Base):
    __tablename__ = "quality_test_design_batch_reservations"
    invocation_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    scope_revision_id = Column(String, nullable=False)
    plan_digest = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["scope_revision_id"], ["quality_test_design_scope_revisions.revision_id"]),
    )


class GenerationBatchCallRecord(Base):
    __tablename__ = "quality_test_design_batch_calls"
    invocation_id = Column(String, primary_key=True)
    sequence = Column(Integer, primary_key=True)
    project_id = Column(String, nullable=False)
    batch_digest = Column(String, nullable=False)
    call_id = Column(String, nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("invocation_id", "sequence", "call_id"),
        UniqueConstraint("invocation_id", "batch_digest"),
        CheckConstraint("sequence >= 0 AND sequence < 64", name="ck_generation_batch_call_sequence"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_test_design_batch_reservations.project_id", "quality_test_design_batch_reservations.invocation_id"]),
    )


class GenerationBatchReplyRecord(Base):
    __tablename__ = "quality_test_design_batch_replies"
    invocation_id = Column(String, primary_key=True)
    sequence = Column(Integer, primary_key=True)
    project_id = Column(String, nullable=False)
    batch_digest = Column(String, nullable=False)
    call_id = Column(String, nullable=False, unique=True)
    artifact_ref = Column(String, nullable=False)
    artifact_hash = Column(String, nullable=False)
    response_hash = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("invocation_id", "sequence", "call_id", name="uq_generation_batch_reply_call_pin"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_test_design_batch_reservations.project_id", "quality_test_design_batch_reservations.invocation_id"]),
        ForeignKeyConstraint(["invocation_id", "sequence", "call_id"],
            ["quality_test_design_batch_calls.invocation_id", "quality_test_design_batch_calls.sequence", "quality_test_design_batch_calls.call_id"]),
        ForeignKeyConstraint(["call_id"], ["llm_calls.id"]),
    )
