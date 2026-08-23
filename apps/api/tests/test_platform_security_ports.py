from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import delete

from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.account_models import AuthLoginRequest, UserProfile
from apps.api.app.application.platform.accounts import AccountApplicationService
from apps.api.app.application.platform.approval_verifier import (
    ToolApprovalVerifierApplicationService,
)
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.application.platform.project_models import ProjectCard, VersionSummary
from apps.api.app.application.quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
)
from apps.api.app.infrastructure.platform.account_runtime import (
    CallableCurrentUserProvider,
)
from apps.api.app.infrastructure.platform.approval_verification import (
    ProjectedToolApprovalVerificationState,
    SQLAlchemyToolApprovalVerificationState,
    ToolApprovalVerificationFacts,
)
from apps.api.app.infrastructure.platform.governance_repository import (
    SQLAlchemyGovernanceCommandRepository,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import (
    ApprovalRecord,
    ConversationRecord,
    ProjectRecord,
    VersionRecord,
)
from apps.api.app.infrastructure.persistence.project_repository import ProjectRepository
from apps.api.app.infrastructure.persistence.quality_loop_repository import (
    QualityLoopRepository,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


class IdentityAdapter:
    def __init__(self, user: UserProfile) -> None:
        self.user = user
        self.login_calls: list[tuple[str, str]] = []

    def authenticate_token(self, token: str):
        return self.user if token == "valid" else None

    def login(self, *, email: str, password: str, user_agent: str | None = None):
        self.login_calls.append((email, password))
        return SimpleNamespace(
            access_token="access-token",
            expires_at="2026-08-09T00:00:00Z",
            user=self.user,
        )

    def logout(self, token: str) -> bool:
        return token == "valid"


def test_account_service_uses_request_actor_and_identity_ports() -> None:
    actor = UserProfile(
        id="user_security_port",
        name="Security lead",
        email="security@example.com",
        role="qa_lead",
    )
    identities = IdentityAdapter(actor)
    service = AccountApplicationService(
        current_user=CallableCurrentUserProvider(lambda: actor),
        identities=identities,
    )

    session = service.login_user(
        AuthLoginRequest(email=actor.email, password="correct-password")
    )

    assert service.current_user() is actor
    assert service.authenticate_token("valid") is actor
    assert session.access_token == "access-token"
    assert session.user == actor
    assert identities.login_calls == [(actor.email, "correct-password")]


def test_approval_gate_reads_only_project_scoped_governance_facts() -> None:
    conversation = ConversationSession(
        id="conversation_security_port",
        session_id="session_security_port",
        title="Governed operation",
        space_type="project",
        space_id="project_security_port",
        project_id="project_security_port",
    )
    summary = ApprovalSummary(
        id="approval_security_port",
        title="Promote baseline",
        status="approved",
        summary="Approved by QA lead",
    )
    state = ProjectedToolApprovalVerificationState(
        ToolApprovalVerificationFacts(
            conversations={conversation.id: conversation},
            approvals={conversation.project_id: [summary]},
            approval_details={},
        )
    )
    service = ToolApprovalVerifierApplicationService(state)
    invocation = ToolInvocation(
        id="tool_security_port",
        conversation_id=conversation.id,
        tool_id="system_image.baseline.promote",
        status="waiting_approval",
        summary="Waiting for approval",
        input_payload={"approval_id": summary.id},
    )

    assert service.allows_tool_invocation(invocation) == (
        True,
        "Approval approval_security_port is approved.",
    )

    invocation.input_payload["approval_id"] = "approval_other"
    assert service.allows_tool_invocation(invocation) == (
        False,
        "Approval approval_other is not attached to project project_security_port.",
    )


def test_approval_detail_status_overrides_stale_summary_projection() -> None:
    summary = ApprovalSummary(
        id="approval_detail_port",
        title="Release decision",
        status="approved",
        summary="Stale summary",
    )
    detail = ApprovalDetail(
        **summary.model_dump(exclude={"status"}),
        status="pending",
        policy_reason="Evidence is incomplete",
        recommended_resolution="Collect evidence",
    )
    state = ProjectedToolApprovalVerificationState(
        ToolApprovalVerificationFacts(
            conversations={},
            approvals={"project_detail_port": [summary]},
            approval_details={detail.id: detail},
        )
    )
    service = ToolApprovalVerifierApplicationService(state)
    invocation = ToolInvocation(
        id="tool_detail_port",
        tool_id="release.decision.submit",
        status="waiting_approval",
        summary="Waiting",
        input_payload={
            "project_id": "project_detail_port",
            "approval_id": detail.id,
        },
    )

    assert service.allows_tool_invocation(invocation) == (
        False,
        "Approval approval_detail_port is pending; approved status is required.",
    )


def test_sqlalchemy_approval_gate_reads_committed_governance_facts() -> None:
    init_database()
    project_id = "project_sql_approval_security_port"
    conversation = ConversationSession(
        id="conversation_sql_approval_security_port",
        session_id="session_sql_approval_security_port",
        title="Durable governed operation",
        space_type="project",
        space_id=project_id,
        project_id=project_id,
    )
    approval = ApprovalDetail(
        id="approval_sql_security_port",
        title="Promote durable baseline",
        status="approved",
        summary="Approved from PostgreSQL",
        policy_reason="Required evidence is complete",
        recommended_resolution="Promote baseline",
    )
    conversations = ConversationRepository()
    approvals = QualityLoopRepository()
    invocation = ToolInvocation(
        id="tool_sql_security_port",
        conversation_id=conversation.id,
        tool_id="system_image.baseline.promote",
        status="waiting_approval",
        summary="Waiting for durable approval",
        input_payload={"approval_id": approval.id},
    )

    try:
        conversations.upsert_conversation(conversation)
        approvals.replace_approvals(project_id, [approval])
        service = ToolApprovalVerifierApplicationService(
            SQLAlchemyToolApprovalVerificationState(conversations, approvals)
        )

        assert service.allows_tool_invocation(invocation) == (
            True,
            "Approval approval_sql_security_port is approved.",
        )

        approvals.replace_approvals(
            project_id,
            [approval.model_copy(update={"status": "pending"})],
        )
        assert service.allows_tool_invocation(invocation) == (
            False,
            "Approval approval_sql_security_port is pending; approved status is required.",
        )
    finally:
        with session_scope() as session:
            session.execute(
                delete(ApprovalRecord).where(ApprovalRecord.project_id == project_id)
            )
            session.execute(
                delete(ConversationRecord).where(
                    ConversationRecord.id == conversation.id
                )
            )


def test_governance_approval_write_atomically_syncs_pending_counts() -> None:
    init_database()
    project_id = "project_sql_governance_command"
    version_id = "version_sql_governance_command"
    projects = ProjectRepository()
    commands = SQLAlchemyGovernanceCommandRepository()
    first = ApprovalDetail(
        id="approval_sql_governance_first",
        title="First approval",
        status="waiting_approval",
        summary="Waiting",
        policy_reason="Required",
        recommended_resolution="Review",
    )
    second = ApprovalDetail(
        id="approval_sql_governance_second",
        title="Second approval",
        status="waiting_approval",
        summary="Waiting",
        policy_reason="Required",
        recommended_resolution="Review",
    )

    try:
        projects.upsert_project(
            ProjectCard(
                id=project_id,
                name="Governance command",
                code="GOV",
                summary="Atomic approval counters",
                status="active",
                risk="medium",
                progress=50,
                active_version="V1",
                blocked_items=0,
                pending_approvals=0,
                system_image_status="ready",
            )
        )
        projects.upsert_version(
            project_id,
            VersionSummary(
                id=version_id,
                name="V1",
                status="active",
                branch_name="release/v1",
                us_total=1,
                us_closed=0,
                pending_runs=0,
                pending_approvals=0,
            ),
        )

        assert commands.save_approval_and_sync_pending_counts(project_id, first) == 1
        assert commands.save_approval_and_sync_pending_counts(project_id, second) == 2
        assert commands.save_approval_and_sync_pending_counts(
            project_id,
            first.model_copy(update={"status": "approved"}),
        ) == 1

        project = projects.get_project(project_id)
        version = projects.list_versions(project_id)[0]
        assert project is not None
        assert project.pending_approvals == 1
        assert version.pending_approvals == 1
        assert QualityLoopRepository().get_approval_detail(
            project_id,
            first.id,
        ).status == "approved"
    finally:
        with session_scope() as session:
            session.execute(
                delete(ApprovalRecord).where(ApprovalRecord.project_id == project_id)
            )
            session.execute(
                delete(VersionRecord).where(VersionRecord.project_id == project_id)
            )
            session.execute(delete(ProjectRecord).where(ProjectRecord.id == project_id))
