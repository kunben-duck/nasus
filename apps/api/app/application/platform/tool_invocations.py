from __future__ import annotations

from typing import List, Optional

from .tool_models import AuditEvent, ToolDefinition, ToolInvocation, ToolInvocationRequest, ToolResult
from .tool_invocation_ports import (
    ToolInvocationAccessPort,
    ToolInvocationApplicationStatePort,
    ToolInvocationExecutionPort,
    ToolStatusEventPort,
)


class ToolInvocationApplicationService:
    """Platform tool catalog, invocation, and audit query use cases."""

    def __init__(
        self,
        *,
        state: ToolInvocationApplicationStatePort,
        runtime: ToolInvocationExecutionPort,
        authorization: ToolInvocationAccessPort,
        events: ToolStatusEventPort,
    ) -> None:
        self._state = state
        self._runtime = runtime
        self._authorization = authorization
        self._events = events

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._state.list_tools())

    async def create_tool_invocation(self, payload: ToolInvocationRequest) -> ToolInvocation:
        if payload.conversation_id:
            conversation = self._state.get_conversation(payload.conversation_id)
            self._authorization.require_conversation_access(conversation)
        return await self._runtime.create(payload)

    async def execute_tool_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        return await self._runtime.execute(invocation)

    async def gate_tool_invocation_if_needed(self, invocation: ToolInvocation) -> bool:
        return await self._runtime.gate_if_needed(invocation)

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self._runtime.tool_definition(tool_id)

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        invocation = self._state.get_invocation(invocation_id)
        self._authorization.require_invocation_access(invocation)
        return await self._runtime.confirm(invocation_id)

    async def emit_tool_status(
        self,
        invocation_id: str,
        status: str,
        summary: str,
        query_keys: list[list[str]],
        result: ToolResult | None = None,
    ) -> None:
        await self._events.emit_tool_status(invocation_id, status, summary, query_keys, result)

    async def emit_tool_invocation_update(
        self,
        *,
        conversation_id: str,
        invocation: ToolInvocation,
        summary: str | None = None,
    ) -> None:
        await self._events.emit_tool_invocation_update(
            conversation_id=conversation_id,
            invocation=invocation,
            summary=summary,
        )

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        invocation = self._state.get_invocation(invocation_id)
        self._authorization.require_invocation_access(invocation)
        return invocation

    def list_tool_invocations(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        tool_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ToolInvocation]:
        invocations = [
            invocation
            for invocation in self._state.list_invocations()
            if self._authorization.can_access_invocation(invocation)
        ]
        if conversation_id is not None:
            invocations = [item for item in invocations if item.conversation_id == conversation_id]
        if agent_goal_id is not None:
            invocations = [
                item
                for item in invocations
                if item.input_payload.get("agent_goal_id") == agent_goal_id
            ]
        if tool_id is not None:
            canonical_tool_id = self._runtime.canonical_tool_id(tool_id)
            invocations = [item for item in invocations if item.tool_id == canonical_tool_id]
        if status is not None:
            invocations = [item for item in invocations if item.status == status]
        return sorted(invocations, key=self.tool_invocation_created_at)

    def tool_invocation_created_at(self, invocation: ToolInvocation) -> str:
        created_events = [
            event.occurred_at
            for event in self._state.list_audit_events()
            if event.tool_invocation_id == invocation.id
            and event.action == "tool.invocation.created"
        ]
        return min(created_events) if created_events else invocation.id

    def list_audit_events(
        self,
        *,
        conversation_id: str | None = None,
        tool_invocation_id: str | None = None,
        agent_goal_id: str | None = None,
    ) -> List[AuditEvent]:
        events = [
            event
            for event in self._state.list_audit_events()
            if self._authorization.can_access_audit_event(event)
        ]
        if conversation_id is not None:
            events = [event for event in events if event.conversation_id == conversation_id]
        if tool_invocation_id is not None:
            events = [event for event in events if event.tool_invocation_id == tool_invocation_id]
        if agent_goal_id is not None:
            events = [event for event in events if event.agent_goal_id == agent_goal_id]
        return sorted(events, key=lambda event: event.occurred_at)
