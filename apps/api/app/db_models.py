from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SettingsRecord(Base):
    __tablename__ = "studio_settings"

    settings_id: Mapped[int] = mapped_column(primary_key=True, default=1)
    language: Mapped[str] = mapped_column(default="zh")
    theme: Mapped[str] = mapped_column(default="dark")
    notification_mode: Mapped[str] = mapped_column(default="important")
    model_preset: Mapped[str] = mapped_column(default="system_default")
    custom_model: Mapped[dict] = mapped_column(JSON, default=dict)
    custom_api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending", index=True)
    summary: Mapped[str]
    steps: Mapped[list] = mapped_column(JSON, default=list)
    autonomy_level: Mapped[str] = mapped_column(default="semi_auto")
    max_steps: Mapped[int] = mapped_column(default=50)
    steps_completed: Mapped[int] = mapped_column(default=0)
    pause_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(nullable=True)


class AgentSwarmRunRecord(Base):
    __tablename__ = "agent_swarm_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    parent_goal_id: Mapped[str] = mapped_column(index=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    swarm_kind: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    max_parallel_agents: Mapped[int] = mapped_column(default=3)
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
    confidence: Mapped[float] = mapped_column(default=0)
    summary: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(index=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)


class ToolInvocationRecord(Base):
    __tablename__ = "tool_invocations"

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
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    failure_summary: Mapped[str] = mapped_column(default="")
    healing_status: Mapped[str] = mapped_column(default="not_started")
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
    ingestion_status: Mapped[str] = mapped_column(default="pending", index=True)
    content_hash: Mapped[str] = mapped_column(default="")
    content_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    last_ingested_at: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
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
