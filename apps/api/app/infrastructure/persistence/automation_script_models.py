from sqlalchemy import Column, ForeignKeyConstraint, JSON, String, UniqueConstraint, CheckConstraint

from .database import Base


class AutomationCallReservationRecord(Base):
    __tablename__ = "quality_automation_call_reservations"
    invocation_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    generation_id = Column(String, nullable=False)
    mapping_revision_id = Column(String, nullable=False)
    case_approval_revision_id = Column(String, nullable=True)
    case_approval_artifact_hash = Column(String, nullable=True)
    call_id = Column(String, nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"), UniqueConstraint("invocation_id", "call_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "generation_id", "mapping_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id",
             "quality_test_design_mapping_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "generation_id", "case_approval_revision_id"],
            ["quality_case_approval_revisions.project_id", "quality_case_approval_revisions.generation_id",
             "quality_case_approval_revisions.revision_id"], name="fk_automation_case_admission"),
        CheckConstraint("(case_approval_revision_id IS NULL) = (case_approval_artifact_hash IS NULL)",
            name="ck_automation_case_admission_pair"),
    )


class AutomationNativeReplyRecord(Base):
    __tablename__ = "quality_automation_native_replies"
    invocation_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    call_id = Column(String, nullable=False, unique=True)
    artifact_ref = Column(String, nullable=False)
    artifact_hash = Column(String, nullable=False)
    response_hash = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_automation_call_reservations.project_id", "quality_automation_call_reservations.invocation_id"]),
        ForeignKeyConstraint(["invocation_id", "call_id"],
            ["quality_automation_call_reservations.invocation_id", "quality_automation_call_reservations.call_id"]),
        ForeignKeyConstraint(["call_id"], ["llm_calls.id"]),
    )


class AutomationScriptRevisionRecord(Base):
    __tablename__ = "quality_automation_script_revisions"
    script_revision_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    invocation_id = Column(String, nullable=False, unique=True)
    call_id = Column(String, nullable=False)
    artifact_ref = Column(String, nullable=False)
    artifact_hash = Column(String, nullable=False)
    response_hash = Column(String, nullable=False)
    status = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    content_hash = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "script_revision_id"),
        ForeignKeyConstraint(["project_id", "invocation_id"],
            ["quality_automation_native_replies.project_id", "quality_automation_native_replies.invocation_id"]),
        ForeignKeyConstraint(["invocation_id", "call_id"],
            ["quality_automation_call_reservations.invocation_id", "quality_automation_call_reservations.call_id"]),
        CheckConstraint("status = 'draft'"),
    )
