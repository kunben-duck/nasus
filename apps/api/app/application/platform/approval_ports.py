from __future__ import annotations

from typing import Protocol

from .tool_models import ToolInvocation


class ToolApprovalVerificationStatePort(Protocol):
    """Read boundary for the minimum governance facts required by a gate."""

    def project_id_for_invocation(self, invocation: ToolInvocation) -> str:
        ...

    def approval_status(self, project_id: str, approval_id: str) -> str | None:
        ...


__all__ = ["ToolApprovalVerificationStatePort"]
