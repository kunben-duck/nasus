from __future__ import annotations

from typing import Any, Protocol

from ...domain.platform.rbac import AuthorizationDecision
from ...domain.platform.tool_governance import ToolGateDecision
from .tool_models import AuditEvent, ToolDefinition, ToolInvocation


class ToolInvocationRuntimeStatePort(Protocol):
    """Durable command-state boundary used by the canonical tool runtime."""

    def create_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        """Atomically create or return the invocation owning its idempotency key."""
        ...

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        ...

    def list_invocations(self) -> list[ToolInvocation]:
        ...

    def find_idempotent_invocation(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        ...

    def claim_for_execution(
        self,
        invocation_id: str,
        *,
        expected_statuses: tuple[str, ...],
        input_updates: dict[str, Any] | None = None,
    ) -> ToolInvocation | None:
        """Atomically move one eligible invocation into running state."""
        ...

    def persist_invocation(self, invocation: ToolInvocation) -> None:
        ...


class ToolCatalogRuntimePort(Protocol):
    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        ...


class ToolAuthorizationRuntimePort(Protocol):
    def authorize(
        self,
        invocation: ToolInvocation,
        tool: ToolDefinition | None,
    ) -> AuthorizationDecision:
        ...

    def current_actor_id(self) -> str:
        ...


class ToolGovernanceRuntimePort(Protocol):
    def evaluate(
        self,
        tool: ToolDefinition | None,
        invocation: ToolInvocation,
    ) -> ToolGateDecision:
        ...


class ToolAuditRuntimePort(Protocol):
    def record_audit_event(self, event: AuditEvent) -> None:
        ...


class AgentReplyRuntimePort(Protocol):
    async def append_assistant_message(
        self,
        *,
        conversation_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        ...


class ToolInvocationEventRuntimePort(Protocol):
    async def emit_tool_invocation_update(
        self,
        *,
        conversation_id: str,
        invocation: ToolInvocation,
        summary: str | None = None,
    ) -> None:
        ...


__all__ = [
    "AgentReplyRuntimePort",
    "ToolAuditRuntimePort",
    "ToolAuthorizationRuntimePort",
    "ToolCatalogRuntimePort",
    "ToolGovernanceRuntimePort",
    "ToolInvocationEventRuntimePort",
    "ToolInvocationRuntimeStatePort",
]
