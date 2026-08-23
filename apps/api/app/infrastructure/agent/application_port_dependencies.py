from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, MutableMapping, Sequence

from ...application.platform.tool_models import ToolDefinition


RuntimeCallable = Callable[..., Any]


@dataclass(frozen=True)
class AgentApplicationProjectionState:
    projects: MutableMapping[str, Any]
    versions: MutableMapping[str, list[Any]]
    us_items: MutableMapping[str, list[Any]]
    conversations: MutableMapping[str, Any]
    conversation_index: MutableMapping[tuple[str, str, str], str]
    conversation_links: MutableMapping[str, Any]
    conversation_summary_checkpoints: MutableMapping[str, Any]
    agent_goals: MutableMapping[str, Any]
    agent_memory_items: MutableMapping[str, Any]
    agent_memory_links: MutableMapping[str, Any]
    session_knowledge_bindings: MutableMapping[str, Any]
    context_object_overlays: MutableMapping[str, list[Any]]
    asset_lanes: MutableMapping[str, list[Any]]
    runs: MutableMapping[str, list[Any]]
    approvals: MutableMapping[str, list[Any]]
    agent_swarms: MutableMapping[str, Any]
    raw_assets: MutableMapping[str, list[Any]]
    knowledge_objects: MutableMapping[str, list[Any]]
    context_relationships: MutableMapping[str, list[Any]]
    quality_metric_snapshots: MutableMapping[str, list[Any]]
    baselines: MutableMapping[str, list[Any]]
    tools: Sequence[ToolDefinition]


@dataclass(frozen=True)
class AgentApplicationPersistenceAdapters:
    upsert_conversation: RuntimeCallable
    upsert_conversation_link: RuntimeCallable
    append_message: RuntimeCallable
    upsert_summary_checkpoint: RuntimeCallable
    upsert_memory_item: RuntimeCallable
    upsert_memory_link: RuntimeCallable
    upsert_swarm: RuntimeCallable
    upsert_goal: RuntimeCallable


@dataclass(frozen=True)
class AgentApplicationRuntimeAdapters:
    conversation_summary_fallback: RuntimeCallable
    resolve_conversation_scope: RuntimeCallable
    current_user_id: RuntimeCallable
    require_project_access: RuntimeCallable
    require_conversation_access: RuntimeCallable
    can_access_conversation: RuntimeCallable
    project_goal: RuntimeCallable
    record_goal_audit_event: RuntimeCallable
    append_text_message: RuntimeCallable
    push_goal_event: RuntimeCallable
    push_conversation_event: RuntimeCallable
    maybe_create_summary_checkpoint: RuntimeCallable
    get_conversation: RuntimeCallable
    plan_message: RuntimeCallable
    create_tool_invocation: RuntimeCallable
    start_goal_from_proposal: RuntimeCallable
    is_confirmation_message: RuntimeCallable
    list_tool_invocations: RuntimeCallable
    is_paused_goal: RuntimeCallable
    resume_goal: RuntimeCallable
    get_tool_invocation: RuntimeCallable
    confirm_tool_invocation: RuntimeCallable
    active_goal_for_conversation: RuntimeCallable
    get_goal: RuntimeCallable
    get_checkpoint: RuntimeCallable
    list_agent_memory_items: RuntimeCallable
    list_audit_events: RuntimeCallable
    create_goal_record: RuntimeCallable
    create_summary_checkpoint: RuntimeCallable
    record_memory_item: RuntimeCallable
    build_memory_context: RuntimeCallable
    quality_state: RuntimeCallable
    source_binding_incomplete: RuntimeCallable
    accept_remote_goal: RuntimeCallable


__all__ = [
    "AgentApplicationPersistenceAdapters",
    "AgentApplicationProjectionState",
    "AgentApplicationRuntimeAdapters",
]
