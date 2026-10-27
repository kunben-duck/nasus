from __future__ import annotations

from typing import List, Optional

from .errors import PlatformApplicationError
from .tool_receipt_access import RESOURCE_RECEIPT_TOOLS, require_receipt_access
from .tool_models import AuditEvent, ToolDefinition, ToolInvocation, ToolInvocationRequest, ToolResult
from .tool_invocation_ports import (
    ToolInvocationAccessPort,
    ToolInvocationApplicationStatePort,
    ToolInvocationExecutionPort,
    ToolInvocationReadResourcesPort,
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
        read_resources: ToolInvocationReadResourcesPort | None = None,
    ) -> None:
        self._state = state
        self._runtime = runtime
        self._authorization = authorization
        self._events = events
        self._read_resources = read_resources

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._state.list_tools())

    async def create_tool_invocation(self, payload: ToolInvocationRequest) -> ToolInvocation:
        if payload.conversation_id:
            conversation = self._state.get_conversation(payload.conversation_id)
            self._authorization.require_conversation_access(conversation)
        invocation = await self._runtime.create(payload)
        if invocation.status == "completed":
            self._require_read_access(invocation)
        else:
            self._authorization.require_invocation_access(invocation)
        return invocation

    async def execute_tool_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        return await self._runtime.execute(invocation)

    async def gate_tool_invocation_if_needed(self, invocation: ToolInvocation) -> bool:
        return await self._runtime.gate_if_needed(invocation)

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self._runtime.tool_definition(tool_id)

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        invocation = self._state.get_invocation(invocation_id)
        self._authorization.require_invocation_access(invocation)
        result = await self._runtime.confirm(invocation_id)
        if result.status == "completed":
            self._require_read_access(result)
        else:
            self._authorization.require_invocation_access(result)
        return result

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
        self._require_read_access(invocation)
        return invocation

    def _require_read_access(self, invocation: ToolInvocation) -> None:
        self._authorization.require_invocation_access(invocation)
        require_receipt_access(self._read_resources, invocation)

    def _require_batch_read_access(self, invocations: List[ToolInvocation]) -> None:
        if not any(item.tool_id in RESOURCE_RECEIPT_TOOLS for item in invocations):
            return
        current = getattr(self._read_resources, "require_batch_access", None)
        if not callable(current):
            raise PlatformApplicationError("source_receipt_access_unavailable", "Source receipt authorization is unavailable.", 503)
        current(invocations)

    def resolve_owned_tool_invocation(
        self, *, actor_id: str, project_id: str, tool_id: str, request_key: str,
    ) -> ToolInvocation | None:
        """Resolve an actor-scoped original request without executing or scanning history."""
        for value in (actor_id, project_id, tool_id, request_key):
            if (type(value) is not str or not value or len(value) > 128 or value.strip() != value
                    or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)):
                raise PlatformApplicationError("invalid_command_lookup", "Invalid original command lookup.", 422)
        canonical_tool = self._runtime.canonical_tool_id(tool_id)
        scope = f"actor:{actor_id}"
        invocation = self._state.find_idempotent_invocation(
            idempotency_scope=scope, tool_id=canonical_tool, idempotency_key=request_key,
        )
        # Repository scope is not authorization; reject substitutions and recheck current ACL.
        if (invocation is None or invocation.idempotency_scope != scope
                or invocation.tool_id != canonical_tool or invocation.idempotency_key != request_key
                or invocation.input_payload.get("idempotency_key") != request_key
                or invocation.input_payload.get("project_id") != project_id):
            return None
        self._require_read_access(invocation)
        return invocation

    def list_tool_invocations(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        tool_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ToolInvocation]:
        invocations = list(self._state.list_invocations())
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
        # Scope first so a goal read does not verify unrelated private archives.
        # Selected records still undergo fresh resource and project authorization.
        invocations = [item for item in invocations if self._authorization.can_access_invocation(item)]
        visible = []
        for item in invocations:
            try:
                self._require_read_access(item)
            except PlatformApplicationError as exc:
                if exc.status_code != 403:
                    # Only denied records may be omitted. Verification failures
                    # cannot turn unknown history into an empty or partial success.
                    raise
                continue
            visible.append(item)
        invocations = visible
        if not invocations:
            return []
        selected_ids = {item.id for item in invocations}
        created_at: dict[str, str] = {}
        for event in self._state.list_audit_events():
            if event.tool_invocation_id in selected_ids and event.action == "tool.invocation.created":
                ident = event.tool_invocation_id
                created_at[ident] = min(created_at.get(ident, event.occurred_at), event.occurred_at)
        result = sorted(invocations, key=lambda item: created_at.get(item.id, item.id))
        self._require_batch_read_access(result)
        return result

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
        events = list(self._state.list_audit_events())
        if conversation_id is not None:
            events = [event for event in events if event.conversation_id == conversation_id]
        if tool_invocation_id is not None:
            events = [event for event in events if event.tool_invocation_id == tool_invocation_id]
        if agent_goal_id is not None:
            events = [event for event in events if event.agent_goal_id == agent_goal_id]
        events = [event for event in events if self._authorization.can_access_audit_event(event)]
        visible = []
        invocations = {}
        for event in events:
            if event.tool_invocation_id:
                try:
                    invocation = self._state.get_invocation(event.tool_invocation_id)
                    self._require_read_access(invocation)
                except PlatformApplicationError as exc:
                    if exc.status_code != 403:
                        raise
                    continue
                except KeyError:
                    continue
                invocations[invocation.id] = invocation
            visible.append(event)
        events = visible
        result = sorted(events, key=lambda event: event.occurred_at)
        self._require_batch_read_access(list(invocations.values()))
        return result
