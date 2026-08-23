from __future__ import annotations

from typing import Any, Protocol, Sequence

from .tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
    ToolResult,
)


class ToolInvocationApplicationStatePort(Protocol):
    """Read-only projections required by tool invocation application queries."""

    def list_tools(self) -> Sequence[ToolDefinition]: ...

    def get_conversation(self, conversation_id: str) -> Any: ...

    def get_invocation(self, invocation_id: str) -> ToolInvocation: ...

    def list_invocations(self) -> Sequence[ToolInvocation]: ...

    def list_audit_events(self) -> Sequence[AuditEvent]: ...


class ToolInvocationExecutionPort(Protocol):
    async def create(self, payload: ToolInvocationRequest) -> ToolInvocation: ...

    async def execute(self, invocation: ToolInvocation) -> ToolInvocation: ...

    async def gate_if_needed(self, invocation: ToolInvocation) -> bool: ...

    def tool_definition(self, tool_id: str) -> ToolDefinition | None: ...

    async def confirm(self, invocation_id: str) -> ToolInvocation: ...

    def canonical_tool_id(self, tool_id: str) -> str: ...


class ToolInvocationAccessPort(Protocol):
    def require_conversation_access(self, conversation: Any) -> None: ...

    def require_invocation_access(self, invocation: ToolInvocation) -> None: ...

    def can_access_invocation(self, invocation: ToolInvocation) -> bool: ...

    def can_access_audit_event(self, event: AuditEvent) -> bool: ...


class ToolStatusEventPort(Protocol):
    async def emit_tool_status(
        self,
        invocation_id: str,
        status: str,
        summary: str,
        query_keys: list[list[str]],
        result: ToolResult | None = None,
    ) -> None: ...

    async def emit_tool_invocation_update(
        self,
        *,
        conversation_id: str,
        invocation: ToolInvocation,
        summary: str | None = None,
    ) -> None: ...


__all__ = [
    "ToolInvocationAccessPort",
    "ToolInvocationApplicationStatePort",
    "ToolInvocationExecutionPort",
    "ToolStatusEventPort",
]
