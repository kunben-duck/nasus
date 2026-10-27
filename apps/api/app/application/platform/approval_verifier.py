from __future__ import annotations

from .approval_ports import ToolApprovalVerificationStatePort
from .tool_models import ToolInvocation
from .tool_handlers.query_input import query_payload
from ..system_image.publications import PublicationPublishInput, RollbackPublishInput
from ...domain.system_image.publication import PUBLICATION_POLICY, ROLLBACK_POLICY, ROLLBACK_TOOL


class ToolApprovalVerifierApplicationService:
    """Verifies approval-required tool invocations against project governance state."""

    def __init__(self, state: ToolApprovalVerificationStatePort) -> None:
        self._state = state

    def allows_tool_invocation(self, invocation: ToolInvocation) -> tuple[bool, str]:
        approval_id = str(invocation.input_payload.get("approval_id") or "")
        project_id = self._state.project_id_for_invocation(invocation)
        if not project_id:
            return False, f"Approval {approval_id} cannot be verified without project context."

        status = self._state.approval_status(project_id, approval_id)
        if status is None:
            return False, f"Approval {approval_id} is not attached to project {project_id}."

        if status in {"approved", "accepted", "completed"}:
            policy = self._state.approval_policy(project_id, approval_id)
            if policy in {PUBLICATION_POLICY, ROLLBACK_POLICY}:
                rollback = policy == ROLLBACK_POLICY
                if invocation.tool_id != (ROLLBACK_TOOL if rollback else "baseline.promote"):
                    return False, "Image publication approval cannot authorize another tool."
                try:
                    (RollbackPublishInput if rollback else PublicationPublishInput).model_validate(query_payload(invocation.input_payload))
                except ValueError:
                    return False, "Image publication approval requires its exact pinned publication command."
            elif invocation.tool_id == ROLLBACK_TOOL:
                return False, "Image rollback requires a separately scoped rollback approval."
            return True, f"Approval {approval_id} is approved."
        return False, f"Approval {approval_id} is {status or 'unknown'}; approved status is required."
