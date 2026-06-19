from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from .models import AuditEvent, ToolDefinition, ToolInvocation, ToolInvocationRequest, ToolResult
from .tool_invocation_handlers import ToolInvocationHandlerRegistry, build_store_tool_handler_registry

if TYPE_CHECKING:
    from .store import ApplicationStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolInvocationRuntime:
    """Canonical lifecycle runtime for every Nasus business tool action.

    UI actions, chat plans, and Agent Loop steps must all enter through this
    runtime before any domain service or workflow handler is invoked.
    """

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store
        self.handlers: ToolInvocationHandlerRegistry = build_store_tool_handler_registry(store)

    async def create(self, payload: ToolInvocationRequest) -> ToolInvocation:
        canonical_tool_id = self.canonical_tool_id(payload.tool_id)
        if payload.idempotency_key:
            existing = self._find_idempotent_invocation(
                conversation_id=payload.conversation_id,
                tool_id=canonical_tool_id,
                idempotency_key=payload.idempotency_key,
            )
            if existing is not None:
                return existing

        invocation = ToolInvocation(
            id=f"tool_{uuid4().hex[:10]}",
            conversation_id=payload.conversation_id,
            tool_id=canonical_tool_id,
            status="pending",
            summary=f"Preparing {canonical_tool_id}",
            initiator_surface=payload.initiator_surface,
            initiator_actor=payload.initiator_actor,
            target_scope=payload.target_scope,
            input_payload={
                **payload.input,
                **({"idempotency_key": payload.idempotency_key} if payload.idempotency_key else {}),
                **({"requested_tool_id": payload.tool_id} if payload.tool_id != canonical_tool_id else {}),
            },
        )
        self._persist(invocation)
        self._audit(invocation, action="tool.invocation.created", status="pending", summary=invocation.summary)

        if await self.gate_if_needed(invocation):
            return invocation

        await self.execute(invocation)
        return self.store.tool_invocations[invocation.id]

    async def confirm(self, invocation_id: str) -> ToolInvocation:
        invocation = self.store.tool_invocations[invocation_id]
        if invocation.status != "waiting_confirmation":
            return invocation
        invocation.input_payload["confirmed_by_user"] = True
        invocation.input_payload["confirmed_at"] = _now_iso()
        self._persist(invocation)
        self._audit(
            invocation,
            action="tool.invocation.confirmed",
            status="accepted",
            summary=f"User confirmed {invocation.tool_id}",
            actor="user",
            actor_kind="user",
        )
        return await self.execute(invocation)

    async def execute(self, invocation: ToolInvocation) -> ToolInvocation:
        """Dispatch to domain handlers after governance gates have passed."""
        handler = self.handlers.resolve(invocation.tool_id)
        self._audit(invocation, action="tool.invocation.executing", status="running", summary=f"Dispatching {invocation.tool_id}")
        if handler is None:
            invocation.status = "failed"
            invocation.summary = f"Unknown tool: {invocation.tool_id}"
            invocation.result = ToolResult(
                invocation_id=invocation.id,
                status="failed",
                summary=invocation.summary,
            )
            self._persist(invocation)
            self._audit(invocation, action="tool.invocation.failed", status="failed", summary=invocation.summary)
        else:
            try:
                await handler.handle(invocation)
            except Exception as exc:
                invocation.status = "failed"
                invocation.summary = f"Tool {invocation.tool_id} failed: {exc}"
                invocation.result = ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=invocation.summary,
                )
                self._persist(invocation)
                self._audit(
                    invocation,
                    action="tool.invocation.failed",
                    status="failed",
                    summary=invocation.summary,
                    metadata={"error_type": type(exc).__name__},
                )
                return invocation

            final_invocation = self.store.tool_invocations[invocation.id]
            final_action = (
                "tool.invocation.completed"
                if final_invocation.status == "completed"
                else "tool.invocation.failed"
                if final_invocation.status == "failed"
                else "tool.invocation.updated"
            )
            self._audit(
                final_invocation,
                action=final_action,
                status=final_invocation.status,
                summary=final_invocation.summary,
            )
        return self.store.tool_invocations[invocation.id]

    async def gate_if_needed(self, invocation: ToolInvocation) -> bool:
        tool = self.tool_definition(invocation.tool_id)
        gate = self.store.tool_governance.evaluate(tool, invocation)
        if not gate.is_blocking:
            return False

        invocation.status = gate.status
        invocation.summary = gate.summary
        self._persist(invocation)
        self._audit(
            invocation,
            action="tool.invocation.gated",
            status=gate.status,
            summary=gate.summary,
            metadata={
                "confirmation_mode": gate.confirmation_mode,
                "risk_level": gate.risk_level,
            },
        )
        if invocation.conversation_id:
            label = tool.label if tool else invocation.tool_id
            gate_action = "approval" if gate.status == "waiting_approval" else "confirmation"
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    f"**{label}** is a high-risk action and needs {gate_action} before I continue. "
                    f"{'Approve' if gate.status == 'waiting_approval' else 'Confirm'} this tool invocation to proceed: `{invocation.id}`."
                ),
                metadata={
                    "planner_kind": "confirmation_gate",
                    "tool_invocation_id": invocation.id,
                    "tool_id": invocation.tool_id,
                    "confirmation_mode": gate.confirmation_mode,
                    "risk_level": gate.risk_level,
                },
            )
            await self.store._push_event(
                invocation.conversation_id,
                "tool.invocation.updated",
                "tool_invocation",
                invocation.id,
                "replace",
                {"status": invocation.status, "summary": invocation.summary, "tool_id": invocation.tool_id},
                [["conversation", invocation.conversation_id]],
            )
        return True

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        canonical_tool_id = self.canonical_tool_id(tool_id)
        return next((tool for tool in self.store.tools if tool.tool_id == canonical_tool_id), None)

    def _find_idempotent_invocation(
        self,
        *,
        conversation_id: str | None,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        return next(
            (
                invocation
                for invocation in self.store.tool_invocations.values()
                if invocation.conversation_id == conversation_id
                and invocation.tool_id == tool_id
                and invocation.input_payload.get("idempotency_key") == idempotency_key
            ),
            None,
        )

    @staticmethod
    def canonical_tool_id(tool_id: str) -> str:
        aliases = {
            "baseline.initialize": "system_image.baseline.initialize",
        }
        return aliases.get(tool_id, tool_id)

    def _persist(self, invocation: ToolInvocation) -> None:
        self.store.tool_invocations[invocation.id] = invocation
        self.store.conversation_repository.upsert_tool_invocation(invocation)
        self.store._upsert_invocation_in_conversation(invocation)

    def _audit(
        self,
        invocation: ToolInvocation,
        *,
        action: str,
        status: str,
        summary: str,
        actor: str | None = None,
        actor_kind: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        tool = self.tool_definition(invocation.tool_id)
        result = invocation.result
        resolved_actor_kind = actor_kind or invocation.initiator_actor
        resolved_actor = actor or (
            self.store.user.id if invocation.initiator_actor == "user" else invocation.input_payload.get("agent_goal_id", "agent")
        )
        event_metadata = {
            "tool_id": invocation.tool_id,
            "initiator_surface": invocation.initiator_surface,
            "initiator_actor": invocation.initiator_actor,
            "target_scope": invocation.target_scope,
        }
        if tool is not None:
            event_metadata.update(
                {
                    "tool_kind": tool.tool_kind,
                    "risk_level": tool.risk_level,
                    "confirmation_mode": tool.confirmation_mode,
                    "produced_objects": tool.produced_objects,
                }
            )
        if metadata:
            event_metadata.update(metadata)

        agent_goal_id = invocation.input_payload.get("agent_goal_id")
        self.store.record_audit_event(
            AuditEvent(
                id=f"audit_{uuid4().hex[:12]}",
                occurred_at=_now_iso(),
                actor=str(resolved_actor),
                actor_kind=resolved_actor_kind,  # type: ignore[arg-type]
                action=action,
                entity_type="tool_invocation",
                entity_id=invocation.id,
                status=status,  # type: ignore[arg-type]
                summary=summary,
                conversation_id=invocation.conversation_id,
                tool_invocation_id=invocation.id,
                agent_goal_id=agent_goal_id if isinstance(agent_goal_id, str) else None,
                object_refs=result.object_refs if result else [],
                evidence_refs=result.evidence_refs if result else [],
                metadata=event_metadata,
            )
        )
