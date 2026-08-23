from __future__ import annotations

from typing import Optional

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .database import Base


class UserIdentityRecord(Base):
    __tablename__ = "user_identities"

    user_id: Mapped[str] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    display_name: Mapped[str]
    role: Mapped[str] = mapped_column(default="qa_lead", index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="active", index=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_preset: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    avatar_object_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_mime_type: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(index=True)
    updated_at: Mapped[str] = mapped_column(index=True)
    last_login_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)


class AccessSessionRecord(Base):
    __tablename__ = "access_sessions"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    status: Mapped[str] = mapped_column(default="active", index=True)
    created_at: Mapped[str] = mapped_column(index=True)
    expires_at: Mapped[str] = mapped_column(index=True)
    revoked_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    last_seen_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(nullable=True)


class ApiRateLimitWindowRecord(Base):
    __tablename__ = "api_rate_limit_windows"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "window_started_at_epoch",
            name="uq_api_rate_limit_window",
        ),
    )

    scope_key: Mapped[str] = mapped_column(primary_key=True)
    window_started_at_epoch: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    expires_at_epoch: Mapped[int] = mapped_column(BigInteger, index=True)
    updated_at_epoch: Mapped[int] = mapped_column(BigInteger)


class SettingsRecord(Base):
    __tablename__ = "studio_settings"

    settings_id: Mapped[int] = mapped_column(primary_key=True, default=1)
    language: Mapped[str] = mapped_column(default="zh")
    theme: Mapped[str] = mapped_column(default="dark")
    notification_mode: Mapped[str] = mapped_column(default="important")
    model_preset: Mapped[str] = mapped_column(default="system_default")
    custom_model: Mapped[dict] = mapped_column(JSON, default=dict)
    custom_api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ModelProviderConfigRecord(Base):
    __tablename__ = "model_provider_configs"

    config_id: Mapped[str] = mapped_column(primary_key=True)
    route: Mapped[str] = mapped_column(index=True)
    display_name: Mapped[str]
    provider_kind: Mapped[str]
    base_url: Mapped[Optional[str]] = mapped_column(nullable=True)
    model_name: Mapped[str]
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    api_key_masked: Mapped[Optional[str]] = mapped_column(nullable=True)
    last_tested_at: Mapped[str] = mapped_column(index=True)
    last_test_signature: Mapped[str] = mapped_column(index=True)
    last_test_result: Mapped[dict] = mapped_column(JSON, default=dict)
    legacy_imported: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(index=True)
    updated_at: Mapped[str] = mapped_column(index=True)


class ModelRouteSelectionRecord(Base):
    __tablename__ = "model_route_selections"

    route: Mapped[str] = mapped_column(primary_key=True)
    active_source: Mapped[str] = mapped_column(default="system_default")
    active_config_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    updated_at: Mapped[str]


class ModelConfigTestGrantRecord(Base):
    __tablename__ = "model_config_test_grants"

    token_hash: Mapped[str] = mapped_column(primary_key=True)
    route: Mapped[str] = mapped_column(index=True)
    config_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    fingerprint: Mapped[str]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ConversationRecord(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(index=True)
    title: Mapped[str]
    space_type: Mapped[str] = mapped_column(index=True)
    space_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    initiator_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)
    last_message_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    latest_summary_checkpoint_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    merged_into_conversation_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    archived_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    related_conversation_ids: Mapped[list] = mapped_column(JSON, default=list)


class ConversationLinkRecord(Base):
    __tablename__ = "conversation_links"

    id: Mapped[str] = mapped_column(primary_key=True)
    left_conversation_id: Mapped[str] = mapped_column(index=True)
    right_conversation_id: Mapped[str] = mapped_column(index=True)
    link_kind: Mapped[str] = mapped_column(index=True)
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float]
    created_at: Mapped[str] = mapped_column(index=True)


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str]
    status: Mapped[str] = mapped_column(default="completed")
    content_type: Mapped[str] = mapped_column(default="text")
    created_at: Mapped[str] = mapped_column(index=True)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    tool_refs: Mapped[list] = mapped_column(JSON, default=list)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    message_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    stream_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    sequence_max: Mapped[Optional[int]] = mapped_column(nullable=True)


class ConversationSummaryCheckpointRecord(Base):
    __tablename__ = "conversation_summary_checkpoints"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    message_range_start: Mapped[Optional[str]] = mapped_column(nullable=True)
    message_range_end: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    summary_text: Mapped[str]
    summary_object_refs: Mapped[list] = mapped_column(JSON, default=list)
    summary_token_count: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[str] = mapped_column(default="system")
    created_at: Mapped[str] = mapped_column(index=True)


class SessionKnowledgeBindingRecord(Base):
    __tablename__ = "session_knowledge_bindings"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    candidate_object_ref: Mapped[str]
    scope: Mapped[str] = mapped_column(default="session_only")
    created_at: Mapped[str] = mapped_column(index=True)


class AgentGoalRecord(Base):
    __tablename__ = "agent_goals"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    goal_template: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    goal_description: Mapped[Optional[str]] = mapped_column(nullable=True)
    target_refs: Mapped[list] = mapped_column(JSON, default=list)
    query_keys: Mapped[list] = mapped_column(JSON, default=list)
    planner_kind: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    planning_summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending", index=True)
    summary: Mapped[str]
    steps: Mapped[list] = mapped_column(JSON, default=list)
    autonomy_level: Mapped[str] = mapped_column(default="semi_auto")
    max_steps: Mapped[int] = mapped_column(default=50)
    max_model_calls: Mapped[int] = mapped_column(default=32)
    max_thinking_tokens: Mapped[int] = mapped_column(default=500_000)
    max_runtime_seconds: Mapped[int] = mapped_column(default=1_800)
    max_no_progress_observations: Mapped[int] = mapped_column(default=3)
    steps_completed: Mapped[int] = mapped_column(default=0)
    model_calls_used: Mapped[int] = mapped_column(default=0)
    thinking_input_tokens_used: Mapped[int] = mapped_column(default=0)
    thinking_output_tokens_used: Mapped[int] = mapped_column(default=0)
    thinking_tokens_used: Mapped[int] = mapped_column(default=0)
    no_progress_observations: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    last_progress_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    last_progress_fingerprint: Mapped[Optional[str]] = mapped_column(nullable=True)
    budget_exhausted_reason: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    pause_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(nullable=True)


class AgentMemoryItemRecord(Base):
    __tablename__ = "agent_memory_items"

    id: Mapped[str] = mapped_column(primary_key=True)
    memory_scope: Mapped[str] = mapped_column(index=True)
    owner_ref: Mapped[str] = mapped_column(index=True)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="active", index=True)
    expires_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(index=True)


class AgentMemoryLinkRecord(Base):
    __tablename__ = "agent_memory_links"

    id: Mapped[str] = mapped_column(primary_key=True)
    memory_id: Mapped[str] = mapped_column(index=True)
    target_ref: Mapped[str] = mapped_column(index=True)
    link_kind: Mapped[str] = mapped_column(index=True)
    confidence: Mapped[float] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(index=True)


class AgentSwarmRunRecord(Base):
    __tablename__ = "agent_swarm_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    parent_goal_id: Mapped[str] = mapped_column(index=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    swarm_kind: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    max_parallel_agents: Mapped[int] = mapped_column(default=3)
    budget_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    merge_strategy: Mapped[str] = mapped_column(default="confidence_weighted")
    target_refs: Mapped[list] = mapped_column(JSON, default=list)
    result_summary: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(index=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)


class AgentWorkerAssignmentRecord(Base):
    __tablename__ = "agent_worker_assignments"

    id: Mapped[str] = mapped_column(primary_key=True)
    swarm_run_id: Mapped[str] = mapped_column(index=True)
    worker_agent_kind: Mapped[str] = mapped_column(index=True)
    target_refs: Mapped[list] = mapped_column(JSON, default=list)
    input_context_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    agent_goal_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    tool_invocation_refs: Mapped[list] = mapped_column(JSON, default=list)
    candidate_result_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(default=120)
    confidence: Mapped[float] = mapped_column(default=0)
    summary: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(index=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)


class ToolInvocationRecord(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_scope",
            "tool_id",
            "idempotency_key",
            name="uq_tool_invocation_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    tool_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    summary: Mapped[str]
    initiator_surface: Mapped[str] = mapped_column(default="ui")
    initiator_actor: Mapped[str] = mapped_column(default="user")
    target_scope: Mapped[str] = mapped_column(default="central")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    idempotency_scope: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    idempotency_fingerprint: Mapped[Optional[str]] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(primary_key=True)
    occurred_at: Mapped[str] = mapped_column(index=True)
    actor: Mapped[str] = mapped_column(index=True)
    actor_kind: Mapped[str] = mapped_column(default="system", index=True)
    action: Mapped[str] = mapped_column(index=True)
    entity_type: Mapped[str] = mapped_column(index=True)
    entity_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="accepted", index=True)
    summary: Mapped[str]
    conversation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    tool_invocation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    agent_goal_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class LLMCallRecord(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    route: Mapped[str] = mapped_column(index=True)
    purpose: Mapped[str] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(index=True)
    model_name: Mapped[str] = mapped_column(index=True)
    selected_provider: Mapped[str]
    selected_model_name: Mapped[str]
    runtime_mode: Mapped[str] = mapped_column(index=True)
    outcome: Mapped[str] = mapped_column(index=True)
    reason: Mapped[str]
    prompt_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    agent_goal_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    tool_invocation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_token_count: Mapped[int] = mapped_column(Integer, default=0)
    output_token_count: Mapped[int] = mapped_column(Integer, default=0)
    usage_source: Mapped[str] = mapped_column(default="none")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_item_count: Mapped[int] = mapped_column(Integer, default=0)
    output_item_count: Mapped[int] = mapped_column(Integer, default=0)
    request_hash: Mapped[str] = mapped_column(index=True)
    response_hash: Mapped[str]


class PromptDefinitionRecord(Base):
    __tablename__ = "prompt_definitions"

    prompt_id: Mapped[str] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    purpose: Mapped[str] = mapped_column(Text)
    input_schema_ref: Mapped[str]
    output_schema_ref: Mapped[str]
    safety_rules_ref: Mapped[str]
    rollback_to: Mapped[Optional[str]] = mapped_column(nullable=True)
    system_template: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(index=True)


class PromptSelectionRecord(Base):
    __tablename__ = "prompt_selections"

    prompt_id: Mapped[str] = mapped_column(primary_key=True)
    active_version: Mapped[str]


class SSEEventOutboxRecord(Base):
    __tablename__ = "sse_event_outbox"

    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(unique=True, index=True)
    event_type: Mapped[str] = mapped_column(index=True)
    occurred_at: Mapped[str] = mapped_column(index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    agent_goal_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    swarm_run_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(index=True)
    entity_id: Mapped[str] = mapped_column(index=True)
    entity_version: Mapped[int] = mapped_column(index=True)
    event_payload: Mapped[dict] = mapped_column(JSON)
    retention_until: Mapped[str] = mapped_column(index=True)


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(index=True)
    code: Mapped[str]
    summary: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft", index=True)
    risk: Mapped[str] = mapped_column(default="low")
    progress: Mapped[int] = mapped_column(default=0)
    active_version: Mapped[str] = mapped_column(default="Not started")
    blocked_items: Mapped[int] = mapped_column(default=0)
    pending_approvals: Mapped[int] = mapped_column(default=0)
    system_image_status: Mapped[str] = mapped_column(default="draft")


class ProjectRoleBindingRecord(Base):
    __tablename__ = "project_role_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_key", name="uq_project_role_binding_user_scope"),
    )

    binding_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(index=True)
    scope_key: Mapped[str] = mapped_column(index=True)
    scope_ref: Mapped[str]
    effective_policy_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="active", index=True)
    created_at: Mapped[str] = mapped_column(index=True)
    updated_at: Mapped[str] = mapped_column(index=True)
    created_by: Mapped[str] = mapped_column(index=True)


class VersionRecord(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft", index=True)
    branch_name: Mapped[str]
    us_total: Mapped[int] = mapped_column(default=0)
    us_closed: Mapped[int] = mapped_column(default=0)
    pending_runs: Mapped[int] = mapped_column(default=0)
    pending_approvals: Mapped[int] = mapped_column(default=0)
    sort_order: Mapped[int] = mapped_column(default=0)


class USWorkItemRecord(Base):
    __tablename__ = "us_work_items"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    title: Mapped[str]
    owner: Mapped[str]
    status: Mapped[str] = mapped_column(default="analysis", index=True)
    risk: Mapped[str] = mapped_column(default="medium")
    progress: Mapped[int] = mapped_column(default=0)
    next_action: Mapped[str] = mapped_column(default="")


class AssetLaneRecord(Base):
    __tablename__ = "asset_lanes"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    us_id: Mapped[str] = mapped_column(index=True)
    label: Mapped[str]
    status: Mapped[str] = mapped_column(default="not_started", index=True)
    summary: Mapped[str]
    updated_at: Mapped[str]
    sort_order: Mapped[int] = mapped_column(default=0)


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="queued", index=True)
    channel: Mapped[str]
    title: Mapped[str]
    summary: Mapped[str]
    started_at: Mapped[str]
    task_context_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    runner_job_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    failure_summary: Mapped[str] = mapped_column(default="")
    healing_status: Mapped[str] = mapped_column(default="not_started")
    healing_depth: Mapped[int] = mapped_column(default=0)
    last_failure_fingerprint: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    target_base_url: Mapped[Optional[str]] = mapped_column(nullable=True)
    automation_asset_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    automation_script_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    execution_plan: Mapped[list] = mapped_column(JSON, default=list)
    execution_timeout_ms: Mapped[int] = mapped_column(default=60_000)
    retry_of_run_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(default=1)
    sort_order: Mapped[int] = mapped_column(default=0)


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="waiting_approval", index=True)
    summary: Mapped[str]
    policy_reason: Mapped[str] = mapped_column(default="")
    conflict_fields: Mapped[list] = mapped_column(JSON, default=list)
    recommended_resolution: Mapped[str] = mapped_column(default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(default=0)


class MergedResolutionRecord(Base):
    __tablename__ = "merged_resolutions"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    object_ref: Mapped[str] = mapped_column(index=True)
    resolution_kind: Mapped[str] = mapped_column(default="structured_3_way")
    status: Mapped[str] = mapped_column(default="pending_merge", index=True)
    base_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    left_candidate_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    right_candidate_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    base_value: Mapped[object] = mapped_column(JSON, nullable=True)
    left_candidate: Mapped[object] = mapped_column(JSON, nullable=True)
    right_candidate: Mapped[object] = mapped_column(JSON, nullable=True)
    merged_value: Mapped[object] = mapped_column(JSON, nullable=True)
    auto_merged_patch: Mapped[list] = mapped_column(JSON, default=list)
    conflict_entries: Mapped[list] = mapped_column(JSON, default=list)
    recommended_resolution: Mapped[str] = mapped_column(Text)
    merged_from: Mapped[list] = mapped_column(JSON, default=list)
    approval_state: Mapped[str] = mapped_column(default="not_requested", index=True)
    approval_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(index=True)
    updated_at: Mapped[str] = mapped_column(index=True)


class KnowledgeObjectRecord(Base):
    __tablename__ = "knowledge_objects"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    type: Mapped[str]
    branch: Mapped[str]
    confidence: Mapped[str]
    relations: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    freshness: Mapped[str]
    sort_order: Mapped[int] = mapped_column(default=0)


class RawAssetRecord(Base):
    __tablename__ = "raw_assets"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(index=True)
    source_uri: Mapped[str]
    source_label: Mapped[Optional[str]] = mapped_column(nullable=True)
    ingestion_status: Mapped[str] = mapped_column(default="pending", index=True)
    content_hash: Mapped[str] = mapped_column(default="")
    content_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    registered_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    registered_by_actor: Mapped[str] = mapped_column(default="system", index=True)
    registered_from_invocation_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    credential_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    permission_status: Mapped[str] = mapped_column(default="not_checked", index=True)
    permission_checked_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    ingest_started_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    last_ingested_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    file_count: Mapped[int] = mapped_column(default=0)
    byte_count: Mapped[int] = mapped_column(default=0)
    sort_order: Mapped[int] = mapped_column(default=0)


class RawAssetChunkRecord(Base):
    __tablename__ = "raw_asset_chunks"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    raw_asset_id: Mapped[str] = mapped_column(index=True)
    source_type: Mapped[str] = mapped_column(index=True)
    chunk_kind: Mapped[str] = mapped_column(index=True)
    section_path: Mapped[str] = mapped_column(index=True)
    content_ref: Mapped[str]
    content_hash: Mapped[str] = mapped_column(index=True)
    token_estimate: Mapped[int] = mapped_column(default=0)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    embedding_record_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class BaselineRecord(Base):
    __tablename__ = "baselines"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)
    source_version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    parent_baseline_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    fork_strategy: Mapped[str] = mapped_column(default="copy_on_write")
    object_count: Mapped[int] = mapped_column(default=0)
    relationship_count: Mapped[int] = mapped_column(default=0)
    metric_snapshot_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class ContextRelationshipRecord(Base):
    __tablename__ = "context_relationships"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    from_object_id: Mapped[str] = mapped_column(index=True)
    relationship_type: Mapped[str] = mapped_column(index=True)
    to_object_id: Mapped[str] = mapped_column(index=True)
    confidence: Mapped[float] = mapped_column(default=0)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(default=0)


class ContextObjectOverlayRecord(Base):
    __tablename__ = "context_object_overlays"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    object_id: Mapped[str] = mapped_column(index=True)
    field_path: Mapped[str]
    operation: Mapped[str] = mapped_column(index=True)
    value_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="candidate", index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class QualityMetricSnapshotRecord(Base):
    __tablename__ = "quality_metric_snapshots"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    metric_group: Mapped[str] = mapped_column(index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    captured_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class EmbeddingRecord(Base):
    __tablename__ = "embedding_records"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    source_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    object_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    chunk_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(index=True)
    embedding_model: Mapped[str]
    embedding_version: Mapped[str]
    provider: Mapped[str] = mapped_column(index=True)
    vector_ref: Mapped[str]
    embedding_vector: Mapped[Optional[list[float]]] = mapped_column(
        Vector().with_variant(JSON(), "sqlite"),
        nullable=True,
    )
    search_text: Mapped[str] = mapped_column(Text, default="")
    dimensions: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(index=True)
    fallback_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class RetrievalRunRecord(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    query: Mapped[str]
    strategy: Mapped[str] = mapped_column(index=True)
    candidate_count: Mapped[int] = mapped_column(default=0)
    result_refs: Mapped[list] = mapped_column(JSON, default=list)
    embedding_record_ids: Mapped[list] = mapped_column(JSON, default=list)
    rerank_record_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class RerankRecord(Base):
    __tablename__ = "rerank_records"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    retrieval_run_id: Mapped[str] = mapped_column(index=True)
    rerank_model: Mapped[str]
    rerank_version: Mapped[str]
    input_count: Mapped[int] = mapped_column(default=0)
    output_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(index=True)
    latency_ms: Mapped[int] = mapped_column(default=0)
    fallback_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class TaskContextRecord(Base):
    __tablename__ = "task_contexts"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    retrieval_run_id: Mapped[str] = mapped_column(index=True)
    summary: Mapped[str]
    readiness: Mapped[str] = mapped_column(index=True)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    relationship_refs: Mapped[list] = mapped_column(JSON, default=list)
    metric_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    missing_context: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(default=0)
    freshness_at: Mapped[str] = mapped_column(index=True)
    context_hash: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class QualityProfileRecord(Base):
    __tablename__ = "quality_profiles"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    task_context_id: Mapped[str] = mapped_column(index=True)
    risk_score: Mapped[int] = mapped_column(default=0)
    coverage_score: Mapped[int] = mapped_column(default=0)
    release_score: Mapped[int] = mapped_column(default=0)
    automation_feasibility: Mapped[int] = mapped_column(default=0)
    risk_drivers: Mapped[list] = mapped_column(JSON, default=list)
    regression_scope_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(default=0)
    freshness_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class QualityAssetPackRecord(Base):
    __tablename__ = "quality_asset_packs"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    us_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)
    current_revision: Mapped[int] = mapped_column(default=1)
    parts: Mapped[list] = mapped_column(JSON, default=list)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class ExecutionEvidenceRecord(Base):
    __tablename__ = "execution_evidence"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    run_id: Mapped[str] = mapped_column(index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    case_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    evidence_type: Mapped[str] = mapped_column(index=True)
    storage_ref: Mapped[str]
    content_hash: Mapped[str] = mapped_column(index=True)
    producer: Mapped[str] = mapped_column(index=True)
    captured_at: Mapped[str] = mapped_column(index=True)
    redaction_status: Mapped[str] = mapped_column(default="not_required", index=True)
    retention_policy: Mapped[str] = mapped_column(default="project_default")
    sort_order: Mapped[int] = mapped_column(default=0)


class FailureReportRecord(Base):
    __tablename__ = "failure_reports"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    run_id: Mapped[str] = mapped_column(index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    failure_kind: Mapped[str] = mapped_column(index=True)
    failure_fingerprint: Mapped[str] = mapped_column(index=True)
    summary: Mapped[str]
    root_cause: Mapped[str]
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="open", index=True)
    healing_attempt_count: Mapped[int] = mapped_column(default=0)
    fallback_to_human: Mapped[bool] = mapped_column(default=False, index=True)
    cooldown_until: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(index=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class ReleaseDecisionRecord(Base):
    __tablename__ = "release_decisions"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    version_id: Mapped[str] = mapped_column(index=True)
    us_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(index=True)
    score: Mapped[int] = mapped_column(default=0)
    rationale: Mapped[str]
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    approval_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(index=True)


class ReleaseReadinessRecord(Base):
    __tablename__ = "release_readiness"

    version_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str]
    score: Mapped[int] = mapped_column(default=0)
    blockers: Mapped[int] = mapped_column(default=0)
    approvals_open: Mapped[int] = mapped_column(default=0)
    pending_merge: Mapped[int] = mapped_column(default=0)
    execution_health: Mapped[str]
    summary: Mapped[str]
    blocker_items: Mapped[list] = mapped_column(JSON, default=list)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_summary: Mapped[dict] = mapped_column(JSON, default=dict)
