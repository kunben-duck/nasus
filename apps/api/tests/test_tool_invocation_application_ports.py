from __future__ import annotations

import asyncio
from types import SimpleNamespace

from apps.api.app.application.platform.tool_invocations import (
    ToolInvocationApplicationService,
)
from apps.api.app.application.platform.tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
)


class ToolApplicationState:
    def __init__(self) -> None:
        self.tools = [
            ToolDefinition(
                tool_id="run.progress.get",
                label="Get run progress",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Read current run progress.",
            )
        ]
        self.conversations = {
            "conversation_tool_app": SimpleNamespace(id="conversation_tool_app")
        }
        self.invocations: dict[str, ToolInvocation] = {}
        self.audit_events: list[AuditEvent] = []

    def list_tools(self):
        return tuple(self.tools)

    def get_conversation(self, conversation_id: str):
        return self.conversations[conversation_id]

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        return self.invocations[invocation_id]

    def list_invocations(self):
        return tuple(self.invocations.values())

    def list_audit_events(self):
        return tuple(self.audit_events)


class ToolExecutionRuntime:
    def __init__(self, state: ToolApplicationState) -> None:
        self.state = state
        self.created_payloads: list[ToolInvocationRequest] = []
        self.confirmed_ids: list[str] = []

    async def create(self, payload: ToolInvocationRequest) -> ToolInvocation:
        self.created_payloads.append(payload)
        invocation = ToolInvocation(
            id="tool_application_created",
            conversation_id=payload.conversation_id,
            tool_id=self.canonical_tool_id(payload.tool_id),
            status="completed",
            summary="Created through explicit runtime port.",
        )
        self.state.invocations[invocation.id] = invocation
        return invocation

    async def execute(self, invocation: ToolInvocation) -> ToolInvocation:
        return invocation

    async def gate_if_needed(self, invocation: ToolInvocation) -> bool:
        return False

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        canonical = self.canonical_tool_id(tool_id)
        return next(
            (tool for tool in self.state.tools if tool.tool_id == canonical),
            None,
        )

    async def confirm(self, invocation_id: str) -> ToolInvocation:
        self.confirmed_ids.append(invocation_id)
        return self.state.invocations[invocation_id]

    def canonical_tool_id(self, tool_id: str) -> str:
        return {
            "query.run.status": "run.progress.get",
        }.get(tool_id, tool_id)


class ToolAccess:
    def __init__(self) -> None:
        self.conversations: list[str] = []
        self.invocations: list[str] = []
        self.denied_invocation_ids: set[str] = set()

    def require_conversation_access(self, conversation) -> None:
        self.conversations.append(conversation.id)

    def require_invocation_access(self, invocation: ToolInvocation) -> None:
        self.invocations.append(invocation.id)

    def can_access_invocation(self, invocation: ToolInvocation) -> bool:
        return invocation.id not in self.denied_invocation_ids

    def can_access_audit_event(self, event: AuditEvent) -> bool:
        return event.tool_invocation_id not in self.denied_invocation_ids


class ToolEvents:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str]] = []
        self.updates: list[dict[str, object]] = []

    async def emit_tool_status(
        self,
        invocation_id: str,
        status: str,
        summary: str,
        query_keys: list[list[str]],
        result=None,
    ) -> None:
        self.statuses.append((invocation_id, status))

    async def emit_tool_invocation_update(self, **payload) -> None:
        self.updates.append(payload)


def build_service():
    state = ToolApplicationState()
    runtime = ToolExecutionRuntime(state)
    access = ToolAccess()
    events = ToolEvents()
    service = ToolInvocationApplicationService(
        state=state,
        runtime=runtime,
        authorization=access,
        events=events,
    )
    return service, state, runtime, access, events


def test_create_and_confirm_use_explicit_runtime_and_access_ports() -> None:
    service, _, runtime, access, _ = build_service()

    invocation = asyncio.run(
        service.create_tool_invocation(
            ToolInvocationRequest(
                conversation_id="conversation_tool_app",
                tool_id="query.run.status",
            )
        )
    )
    confirmed = asyncio.run(service.confirm_tool_invocation(invocation.id))

    assert access.conversations == ["conversation_tool_app"]
    assert access.invocations == [invocation.id]
    assert runtime.created_payloads[0].tool_id == "query.run.status"
    assert runtime.confirmed_ids == [invocation.id]
    assert confirmed.id == invocation.id
    assert confirmed.tool_id == "run.progress.get"


def test_query_filters_canonical_tool_id_authorization_and_created_time() -> None:
    service, state, _, access, _ = build_service()
    visible = ToolInvocation(
        id="tool_visible",
        conversation_id="conversation_tool_app",
        tool_id="run.progress.get",
        status="completed",
        summary="Visible",
        input_payload={"agent_goal_id": "goal_visible"},
    )
    hidden = ToolInvocation(
        id="tool_hidden",
        conversation_id="conversation_tool_app",
        tool_id="run.progress.get",
        status="completed",
        summary="Hidden",
        input_payload={"agent_goal_id": "goal_visible"},
    )
    state.invocations = {hidden.id: hidden, visible.id: visible}
    access.denied_invocation_ids.add(hidden.id)
    state.audit_events.extend(
        [
            AuditEvent(
                id="audit_hidden",
                occurred_at="2026-01-02T00:00:00+00:00",
                actor="system",
                action="tool.invocation.created",
                entity_type="tool_invocation",
                entity_id=hidden.id,
                summary="Created",
                tool_invocation_id=hidden.id,
            ),
            AuditEvent(
                id="audit_visible",
                occurred_at="2026-01-01T00:00:00+00:00",
                actor="system",
                action="tool.invocation.created",
                entity_type="tool_invocation",
                entity_id=visible.id,
                summary="Created",
                tool_invocation_id=visible.id,
            ),
        ]
    )

    invocations = service.list_tool_invocations(
        conversation_id="conversation_tool_app",
        agent_goal_id="goal_visible",
        tool_id="query.run.status",
        status="completed",
    )
    audits = service.list_audit_events(agent_goal_id=None)

    assert [item.id for item in invocations] == [visible.id]
    assert [event.id for event in audits] == ["audit_visible"]


def test_status_and_update_events_use_the_event_port() -> None:
    service, state, _, _, events = build_service()
    invocation = ToolInvocation(
        id="tool_event",
        conversation_id="conversation_tool_app",
        tool_id="run.progress.get",
        status="running",
        summary="Running",
    )
    state.invocations[invocation.id] = invocation

    asyncio.run(
        service.emit_tool_status(
            invocation.id,
            "completed",
            "Completed",
            [["conversation", "conversation_tool_app"]],
        )
    )
    asyncio.run(
        service.emit_tool_invocation_update(
            conversation_id="conversation_tool_app",
            invocation=invocation,
            summary="Updated",
        )
    )

    assert events.statuses == [(invocation.id, "completed")]
    assert events.updates == [
        {
            "conversation_id": "conversation_tool_app",
            "invocation": invocation,
            "summary": "Updated",
        }
    ]
