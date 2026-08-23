from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from ...domain.platform.rbac import AuthorizationDecision
from .errors import PlatformApplicationError
from .tool_models import AuditEvent, ToolDefinition, ToolInvocation, ToolInvocationRequest, ToolResult
from .runtime_ports import (
    AgentReplyRuntimePort,
    ToolAuditRuntimePort,
    ToolAuthorizationRuntimePort,
    ToolCatalogRuntimePort,
    ToolGovernanceRuntimePort,
    ToolInvocationEventRuntimePort,
    ToolInvocationRuntimeStatePort,
)
from .tool_handlers import ToolInvocationHandlerRegistry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolInvocationRuntime:
    """Canonical lifecycle runtime for every Nasus business tool action.

    UI actions, chat plans, and Agent Loop steps must all enter through this
    runtime before any domain service or workflow handler is invoked.
    """

    def __init__(
        self,
        *,
        state: ToolInvocationRuntimeStatePort,
        catalog: ToolCatalogRuntimePort,
        authorization: ToolAuthorizationRuntimePort,
        governance: ToolGovernanceRuntimePort,
        audit_events: ToolAuditRuntimePort,
        agent_replies: AgentReplyRuntimePort,
        events: ToolInvocationEventRuntimePort,
        handlers: ToolInvocationHandlerRegistry,
    ) -> None:
        self._state = state
        self._catalog = catalog
        self._authorization = authorization
        self._governance = governance
        self._audit_events = audit_events
        self._agent_replies = agent_replies
        self._events = events
        self.handlers = handlers

    async def create(self, payload: ToolInvocationRequest) -> ToolInvocation:
        canonical_tool_id = self.canonical_tool_id(payload.tool_id)
        sanitized_input = self._sanitize_client_input(payload.input)
        idempotency_scope = self._idempotency_scope(payload)
        idempotency_fingerprint = self._idempotency_fingerprint(
            payload,
            canonical_tool_id=canonical_tool_id,
            sanitized_input=sanitized_input,
        )
        if payload.idempotency_key:
            existing = self._state.find_idempotent_invocation(
                idempotency_scope=idempotency_scope,
                tool_id=canonical_tool_id,
                idempotency_key=payload.idempotency_key,
            )
            if existing is not None:
                self._assert_idempotency_payload_matches(
                    existing,
                    idempotency_fingerprint=idempotency_fingerprint,
                )
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
                **sanitized_input,
                **({"idempotency_key": payload.idempotency_key} if payload.idempotency_key else {}),
                **({"requested_tool_id": payload.tool_id} if payload.tool_id != canonical_tool_id else {}),
            },
            idempotency_scope=idempotency_scope if payload.idempotency_key else None,
            idempotency_key=payload.idempotency_key,
            idempotency_fingerprint=(
                idempotency_fingerprint if payload.idempotency_key else None
            ),
        )
        claimed_invocation = self._state.create_invocation(invocation)
        if claimed_invocation.id != invocation.id:
            self._assert_idempotency_payload_matches(
                claimed_invocation,
                idempotency_fingerprint=idempotency_fingerprint,
            )
            return claimed_invocation
        invocation = claimed_invocation
        self._audit(invocation, action="tool.invocation.created", status="pending", summary=invocation.summary)

        authorization = self._authorize(invocation)
        if not authorization.allowed:
            self._deny(invocation, authorization)
            return self._state.get_invocation(invocation.id)

        if await self.gate_if_needed(invocation):
            return invocation

        await self.execute(invocation)
        return self._state.get_invocation(invocation.id)

    async def confirm(self, invocation_id: str) -> ToolInvocation:
        invocation = self._state.get_invocation(invocation_id)
        if invocation.status != "waiting_confirmation":
            return invocation
        invocation = self._state.claim_for_execution(
            invocation_id,
            expected_statuses=("waiting_confirmation",),
            input_updates={
                "confirmed_by_user": True,
                "confirmed_at": _now_iso(),
            },
        )
        if invocation is None:
            return self._state.get_invocation(invocation_id)
        self._audit(
            invocation,
            action="tool.invocation.confirmed",
            status="accepted",
            summary=f"User confirmed {invocation.tool_id}",
            actor="user",
            actor_kind="user",
        )
        return await self._execute_claimed(invocation)

    async def execute(self, invocation: ToolInvocation) -> ToolInvocation:
        """Dispatch to domain handlers after governance gates have passed."""
        claimed = self._state.claim_for_execution(
            invocation.id,
            expected_statuses=("pending",),
        )
        if claimed is None:
            return self._state.get_invocation(invocation.id)
        return await self._execute_claimed(claimed)

    async def _execute_claimed(self, invocation: ToolInvocation) -> ToolInvocation:
        """Execute an invocation after the durable state port won the claim."""
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

            final_invocation = self._state.get_invocation(invocation.id)
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
        return self._state.get_invocation(invocation.id)

    async def gate_if_needed(self, invocation: ToolInvocation) -> bool:
        tool = self.tool_definition(invocation.tool_id)
        gate = self._governance.evaluate(tool, invocation)
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
            await self._agent_replies.append_assistant_message(
                conversation_id=invocation.conversation_id,
                content=(
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
            await self._events.emit_tool_invocation_update(
                conversation_id=invocation.conversation_id,
                invocation=invocation,
            )
        return True

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        canonical_tool_id = self.canonical_tool_id(tool_id)
        return self._catalog.tool_definition(canonical_tool_id)

    def _authorize(self, invocation: ToolInvocation) -> AuthorizationDecision:
        return self._authorization.authorize(invocation, self.tool_definition(invocation.tool_id))

    def _deny(self, invocation: ToolInvocation, authorization: AuthorizationDecision) -> None:
        invocation.status = "failed"
        invocation.summary = authorization.summary
        invocation.input_payload["authorization_denied"] = True
        invocation.input_payload["authorization_required_roles"] = list(authorization.required_roles)
        invocation.input_payload["authorization_user_role"] = authorization.user_role
        invocation.result = ToolResult(
            invocation_id=invocation.id,
            status="failed",
            summary=authorization.summary,
            requires_followup=True,
            followup_reason="authorization_denied",
        )
        self._persist(invocation)
        self._audit(
            invocation,
            action="tool.invocation.authorization_denied",
            status="failed",
            summary=authorization.summary,
            metadata={
                "authorization_required_roles": list(authorization.required_roles),
                "authorization_user_role": authorization.user_role,
            },
        )

    def _idempotency_scope(self, payload: ToolInvocationRequest) -> str:
        if payload.conversation_id:
            return f"conversation:{payload.conversation_id}"
        return f"actor:{self._authorization.current_actor_id()}"

    @staticmethod
    def _idempotency_fingerprint(
        payload: ToolInvocationRequest,
        *,
        canonical_tool_id: str,
        sanitized_input: dict,
    ) -> str:
        canonical_payload = {
            "tool_id": canonical_tool_id,
            "input": sanitized_input,
            "initiator_surface": payload.initiator_surface,
            "initiator_actor": payload.initiator_actor,
            "target_scope": payload.target_scope,
        }
        encoded = json.dumps(
            canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _assert_idempotency_payload_matches(
        invocation: ToolInvocation,
        *,
        idempotency_fingerprint: str,
    ) -> None:
        if (
            invocation.idempotency_fingerprint
            and invocation.idempotency_fingerprint != idempotency_fingerprint
        ):
            raise PlatformApplicationError(
                code="tool_idempotency_conflict",
                message=(
                    "The idempotency key is already bound to a different "
                    "tool invocation payload."
                ),
                status_code=409,
            )

    @staticmethod
    def canonical_tool_id(tool_id: str) -> str:
        aliases = {
            "baseline.initialize": "system_image.baseline.initialize",
            "version.import.us": "version.inputs.import",
            "merge.resolve": "resolution.merge",
            "query.run.status": "run.progress.get",
        }
        return aliases.get(tool_id, tool_id)

    def _persist(self, invocation: ToolInvocation) -> None:
        self._state.persist_invocation(invocation)

    @staticmethod
    def _sanitize_client_input(input_payload: dict) -> dict:
        reserved_fields = {
            "approval_status",
            "approved_at",
            "approved_by",
            "confirmed_at",
            "confirmed_by_user",
            "confirmed_by",
            "policy_snapshot_id",
        }
        return {key: value for key, value in input_payload.items() if key not in reserved_fields}

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
            self._authorization.current_actor_id()
            if invocation.initiator_actor == "user"
            else invocation.input_payload.get("agent_goal_id", "agent")
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
        self._audit_events.record_audit_event(
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
