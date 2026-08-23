from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...application.agent.agent_models import ConversationSession
from ...application.platform.approval_ports import ToolApprovalVerificationStatePort
from ...application.platform.tool_models import ToolInvocation
from ...application.quality_loop.quality_models import ApprovalDetail, ApprovalSummary


class ConversationApprovalScopeRepository(Protocol):
    def get_conversation(
        self,
        conversation_id: str,
    ) -> ConversationSession | None: ...


class ApprovalVerificationRepository(Protocol):
    def get_approval_detail(
        self,
        project_id: str,
        approval_id: str,
    ) -> ApprovalDetail | None: ...


class SQLAlchemyToolApprovalVerificationState(ToolApprovalVerificationStatePort):
    """Verify governance gates from committed conversation and approval facts."""

    def __init__(
        self,
        conversations: ConversationApprovalScopeRepository,
        approvals: ApprovalVerificationRepository,
    ) -> None:
        self._conversations = conversations
        self._approvals = approvals

    def project_id_for_invocation(self, invocation: ToolInvocation) -> str:
        project_id = str(invocation.input_payload.get("project_id") or "")
        if project_id or not invocation.conversation_id:
            return project_id
        conversation = self._conversations.get_conversation(
            invocation.conversation_id
        )
        if conversation is None:
            return ""
        return conversation.project_id or (
            conversation.space_id if conversation.space_type == "project" else ""
        )

    def approval_status(self, project_id: str, approval_id: str) -> str | None:
        approval = self._approvals.get_approval_detail(project_id, approval_id)
        return approval.status if approval is not None else None


@dataclass(frozen=True)
class ToolApprovalVerificationFacts:
    conversations: dict[str, ConversationSession]
    approvals: dict[str, list[ApprovalSummary]]
    approval_details: dict[str, ApprovalDetail]


class ProjectedToolApprovalVerificationState(ToolApprovalVerificationStatePort):
    """Maps compatibility governance projections to the narrow gate contract."""

    def __init__(self, facts: ToolApprovalVerificationFacts) -> None:
        self._facts = facts

    def project_id_for_invocation(self, invocation: ToolInvocation) -> str:
        project_id = str(invocation.input_payload.get("project_id") or "")
        conversation = self._facts.conversations.get(invocation.conversation_id or "")
        if conversation is None:
            return project_id
        return project_id or conversation.project_id or (
            conversation.space_id if conversation.space_type == "project" else ""
        )

    def approval_status(self, project_id: str, approval_id: str) -> str | None:
        approval = next(
            (
                item
                for item in self._facts.approvals.get(project_id, [])
                if item.id == approval_id
            ),
            None,
        )
        if approval is None:
            return None
        detail = self._facts.approval_details.get(approval_id)
        return detail.status if detail is not None else approval.status


__all__ = [
    "ProjectedToolApprovalVerificationState",
    "SQLAlchemyToolApprovalVerificationState",
    "ToolApprovalVerificationFacts",
]
