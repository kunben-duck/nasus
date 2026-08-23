from __future__ import annotations

from .approval_ports import ToolApprovalVerificationStatePort
from .tool_models import ToolInvocation


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
            return True, f"Approval {approval_id} is approved."
        return False, f"Approval {approval_id} is {status or 'unknown'}; approved status is required."
