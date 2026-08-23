from __future__ import annotations

import asyncio

from apps.api.app.application.platform.runtime import ToolInvocationRuntime
from apps.api.app.application.platform.tool_handlers import (
    FunctionToolInvocationHandler,
    ToolInvocationHandlerRegistry,
)
from apps.api.app.application.platform.tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
    ToolResult,
)
from apps.api.app.domain.platform.rbac import AuthorizationDecision
from apps.api.app.domain.platform.tool_governance import ToolGovernance
from apps.api.app.infrastructure.platform.tool_runtime import StaticToolCatalogRuntimeAdapter


class MemoryRuntimeState:
    def __init__(self) -> None:
        self.invocations: dict[str, ToolInvocation] = {}

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        return self.invocations[invocation_id]

    def create_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        existing = self.find_idempotent_invocation(
            idempotency_scope=invocation.idempotency_scope or "",
            tool_id=invocation.tool_id,
            idempotency_key=invocation.idempotency_key or "",
        )
        if existing is not None:
            return existing
        self.persist_invocation(invocation)
        return invocation

    def list_invocations(self) -> list[ToolInvocation]:
        return list(self.invocations.values())

    def find_idempotent_invocation(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        if not idempotency_key:
            return None
        return next(
            (
                invocation
                for invocation in self.invocations.values()
                if invocation.idempotency_scope == idempotency_scope
                and invocation.tool_id == tool_id
                and invocation.idempotency_key == idempotency_key
            ),
            None,
        )

    def claim_for_execution(
        self,
        invocation_id: str,
        *,
        expected_statuses: tuple[str, ...],
        input_updates: dict | None = None,
    ) -> ToolInvocation | None:
        invocation = self.invocations[invocation_id]
        if invocation.status not in expected_statuses:
            return None
        invocation.status = "running"
        invocation.input_payload.update(input_updates or {})
        invocation.revision += 1
        self.persist_invocation(invocation)
        return invocation

    def persist_invocation(self, invocation: ToolInvocation) -> None:
        self.invocations[invocation.id] = invocation


class RuntimeAuthorization:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed

    def authorize(
        self,
        invocation: ToolInvocation,
        tool: ToolDefinition | None,
    ) -> AuthorizationDecision:
        if self.allowed:
            return AuthorizationDecision(
                allowed=True,
                summary="Authorized.",
                required_roles=(),
                user_role="quality_member",
            )
        return AuthorizationDecision(
            allowed=False,
            summary="The actor cannot run this tool.",
            required_roles=("project_admin",),
            user_role="viewer",
        )

    def current_actor_id(self) -> str:
        return "user_runtime_test"


class RuntimeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record_audit_event(self, event: AuditEvent) -> None:
        self.events.append(event)


class RuntimeReplies:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def append_assistant_message(self, **payload):
        self.messages.append(payload)
        return payload


class RuntimeEvents:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    async def emit_tool_invocation_update(self, **payload) -> None:
        self.updates.append(payload)


def tool_definition(*, confirmation_mode: str = "none") -> ToolDefinition:
    return ToolDefinition(
        tool_id="quality.test.execute",
        label="Execute quality test",
        tool_kind="execution",
        scope="central",
        risk_level="high" if confirmation_mode != "none" else "low",
        confirmation_mode=confirmation_mode,
        description="Exercise the canonical runtime lifecycle.",
    )


def build_runtime(
    *,
    tool: ToolDefinition,
    authorization: RuntimeAuthorization | None = None,
) -> tuple[
    ToolInvocationRuntime,
    MemoryRuntimeState,
    RuntimeAudit,
    RuntimeReplies,
    RuntimeEvents,
    list[str],
]:
    state = MemoryRuntimeState()
    audit = RuntimeAudit()
    replies = RuntimeReplies()
    events = RuntimeEvents()
    handled: list[str] = []

    async def complete(invocation: ToolInvocation) -> None:
        handled.append(invocation.id)
        invocation.status = "completed"
        invocation.summary = "Quality test completed."
        invocation.result = ToolResult(
            invocation_id=invocation.id,
            status="completed",
            summary=invocation.summary,
            object_refs=["run:runtime-test"],
        )
        state.persist_invocation(invocation)

    handlers = ToolInvocationHandlerRegistry()
    handlers.register(tool.tool_id, FunctionToolInvocationHandler(complete))
    runtime = ToolInvocationRuntime(
        state=state,
        catalog=StaticToolCatalogRuntimeAdapter([tool]),
        authorization=authorization or RuntimeAuthorization(),
        governance=ToolGovernance(),
        audit_events=audit,
        agent_replies=replies,
        events=events,
        handlers=handlers,
    )
    return runtime, state, audit, replies, events, handled


def test_runtime_reuses_idempotent_invocation_and_preserves_audit_chain() -> None:
    runtime, _, audit, _, _, handled = build_runtime(tool=tool_definition())
    request = ToolInvocationRequest(
        conversation_id="conversation_runtime_test",
        tool_id="quality.test.execute",
        input={"project_id": "project_runtime_test", "approved_by": "spoofed"},
        idempotency_key="runtime-idempotency-key",
    )

    first = asyncio.run(runtime.create(request))
    second = asyncio.run(runtime.create(request))

    assert first.id == second.id
    assert first.status == "completed"
    assert handled == [first.id]
    assert "approved_by" not in first.input_payload
    assert [event.action for event in audit.events] == [
        "tool.invocation.created",
        "tool.invocation.executing",
        "tool.invocation.completed",
    ]
    assert audit.events[-1].object_refs == ["run:runtime-test"]


def test_runtime_rejects_reusing_idempotency_key_for_different_payload() -> None:
    runtime, _, _, _, _, handled = build_runtime(tool=tool_definition())
    first = ToolInvocationRequest(
        conversation_id="conversation_runtime_conflict",
        tool_id="quality.test.execute",
        input={"project_id": "project_one"},
        idempotency_key="shared-key",
    )
    conflicting = first.model_copy(
        update={"input": {"project_id": "project_two"}}
    )

    asyncio.run(runtime.create(first))

    try:
        asyncio.run(runtime.create(conflicting))
    except ValueError as exc:
        assert getattr(exc, "code", None) == "tool_idempotency_conflict"
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("conflicting idempotency payload was accepted")
    assert len(handled) == 1


def test_runtime_confirmation_gate_publishes_message_and_resumes_same_invocation() -> None:
    runtime, _, audit, replies, events, handled = build_runtime(
        tool=tool_definition(confirmation_mode="user_confirm")
    )

    pending = asyncio.run(
        runtime.create(
            ToolInvocationRequest(
                conversation_id="conversation_runtime_gate",
                tool_id="quality.test.execute",
            )
        )
    )

    assert pending.status == "waiting_confirmation"
    assert handled == []
    assert len(replies.messages) == 1
    assert len(events.updates) == 1
    assert audit.events[-1].action == "tool.invocation.gated"

    completed = asyncio.run(runtime.confirm(pending.id))
    duplicate_confirmation = asyncio.run(runtime.confirm(pending.id))

    assert completed.id == pending.id
    assert completed.status == "completed"
    assert handled == [pending.id]
    assert duplicate_confirmation.status == "completed"
    assert "tool.invocation.confirmed" in [event.action for event in audit.events]


def test_runtime_denies_before_handler_dispatch() -> None:
    runtime, _, audit, replies, events, handled = build_runtime(
        tool=tool_definition(),
        authorization=RuntimeAuthorization(allowed=False),
    )

    denied = asyncio.run(
        runtime.create(
            ToolInvocationRequest(
                conversation_id="conversation_runtime_denied",
                tool_id="quality.test.execute",
            )
        )
    )

    assert denied.status == "failed"
    assert denied.result is not None
    assert denied.result.followup_reason == "authorization_denied"
    assert handled == []
    assert replies.messages == []
    assert events.updates == []
    assert audit.events[-1].action == "tool.invocation.authorization_denied"
