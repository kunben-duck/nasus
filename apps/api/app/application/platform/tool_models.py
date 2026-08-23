from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    tool_id: str
    label: str
    tool_kind: str
    scope: Literal["central", "edge", "either"]
    risk_level: Literal["low", "medium", "high", "critical"]
    confirmation_mode: Literal["none", "user_confirm", "approval_required", "policy_only"]
    description: str
    required_context: List[str] = Field(default_factory=list)
    produced_objects: List[str] = Field(default_factory=list)
    input_schema_ref: Optional[str] = None
    output_schema_ref: Optional[str] = None


class ToolResult(BaseModel):
    invocation_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    requires_followup: bool = False
    followup_reason: Optional[str] = None
    followup_prompt: Optional[str] = None
    next_recommended_tools: List[str] = Field(default_factory=list)


class ToolInvocation(BaseModel):
    id: str
    conversation_id: Optional[str] = None
    tool_id: str
    status: Literal["pending", "running", "waiting_confirmation", "waiting_approval", "completed", "failed", "cancelled"]
    summary: str
    initiator_surface: Literal["chat", "ui", "api", "agent_loop"] = "ui"
    initiator_actor: Literal["user", "agent"] = "user"
    target_scope: Literal["central", "edge"] = "central"
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[ToolResult] = None
    # Runtime coordination fields are durable implementation facts, not part
    # of the public ToolInvocation API contract.
    idempotency_scope: Optional[str] = Field(default=None, exclude=True)
    idempotency_key: Optional[str] = Field(default=None, exclude=True)
    idempotency_fingerprint: Optional[str] = Field(default=None, exclude=True)
    revision: int = Field(default=0, exclude=True)


class AuditEvent(BaseModel):
    id: str
    occurred_at: str
    actor: str
    actor_kind: Literal["user", "agent", "system"] = "system"
    action: str
    entity_type: str
    entity_id: str
    status: Literal[
        "accepted",
        "draft",
        "pending",
        "running",
        "paused",
        "blocked",
        "waiting_confirmation",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    ] = "accepted"
    summary: str
    conversation_id: Optional[str] = None
    tool_invocation_id: Optional[str] = None
    agent_goal_id: Optional[str] = None
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolInvocationRequest(BaseModel):
    conversation_id: Optional[str] = None
    tool_id: str
    input: Dict[str, Any] = Field(default_factory=dict)
    initiator_surface: Literal["chat", "ui", "api", "agent_loop"] = "ui"
    initiator_actor: Literal["user", "agent"] = "user"
    target_scope: Literal["central", "edge"] = "central"
    idempotency_key: Optional[str] = None


class EventPayload(BaseModel):
    event_id: str
    event_type: str
    occurred_at: str
    correlation_id: str
    conversation_id: Optional[str] = None
    tool_invocation_id: Optional[str] = None
    agent_goal_id: Optional[str] = None
    agent_step_id: Optional[str] = None
    swarm_run_id: Optional[str] = None
    assignment_id: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    entity_type: str
    entity_id: str
    entity_version: int
    mutation_kind: Literal["replace", "patch", "append", "invalidate"]
    patch: Dict[str, Any] = Field(default_factory=dict)
    query_keys: List[List[str]] = Field(default_factory=list)
    snapshot_hint: bool = False
    payload: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AuditEvent",
    "EventPayload",
    "ToolDefinition",
    "ToolInvocation",
    "ToolInvocationRequest",
    "ToolResult",
]
