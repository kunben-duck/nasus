from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


SpaceType = Literal[
    "welcome",
    "build",
    "dashboard",
    "documentation",
    "project",
    "version",
    "workspace",
    "knowledge",
    "runs",
    "governance",
]


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    role: str


class ProviderStatus(BaseModel):
    provider: Literal["mock", "openai", "gemini", "anthropic", "openai_compatible"]
    available: bool
    configured_via: Literal["builtin", "system_default", "custom"]
    mode: Literal["live", "fallback"] = "fallback"
    fallback_provider: Optional[Literal["mock"]] = None
    reason: str


class CustomModelConfig(BaseModel):
    provider_kind: Literal["openai_compatible", "openai", "gemini", "anthropic"] = "openai_compatible"
    base_url: Optional[str] = None
    model_name: str = ""
    has_api_key: bool = False
    api_key_masked: Optional[str] = None


class StudioSettings(BaseModel):
    language: Literal["en", "zh"] = "en"
    theme: Literal["dark", "light", "system"] = "dark"
    model_preset: Literal["system_default", "custom"] = "system_default"
    notification_mode: Literal["important", "all", "muted"] = "important"
    model_provider: Literal["mock", "openai", "gemini", "anthropic", "openai_compatible"] = "openai"
    model_name: str = "gpt-5.4"
    runtime_mode: Literal["live", "fallback"] = "fallback"
    fallback_provider: Literal["mock"] = "mock"
    provider_statuses: List[ProviderStatus] = Field(default_factory=list)
    active_provider_status: ProviderStatus = Field(
        default_factory=lambda: ProviderStatus(
            provider="openai",
            available=False,
            configured_via="system_default",
            mode="fallback",
            fallback_provider="mock",
            reason="System default provider is not configured.",
        )
    )
    custom_model: CustomModelConfig = Field(default_factory=CustomModelConfig)


class StudioSettingsPatch(BaseModel):
    language: Optional[Literal["en", "zh"]] = None
    theme: Optional[Literal["dark", "light", "system"]] = None
    model_preset: Optional[Literal["system_default", "custom"]] = None
    notification_mode: Optional[Literal["important", "all", "muted"]] = None
    custom_provider_kind: Optional[Literal["openai_compatible", "openai", "gemini", "anthropic"]] = None
    custom_base_url: Optional[str] = None
    custom_model_name: Optional[str] = None
    custom_api_key: Optional[str] = None


class StudioSettingsConnectionTestRequest(BaseModel):
    model_preset: Optional[Literal["system_default", "custom"]] = None
    custom_provider_kind: Optional[Literal["openai_compatible", "openai", "gemini", "anthropic"]] = None
    custom_base_url: Optional[str] = None
    custom_model_name: Optional[str] = None
    custom_api_key: Optional[str] = None


class StudioSettingsConnectionTestResponse(BaseModel):
    ok: bool
    provider: Literal["mock", "openai", "gemini", "anthropic", "openai_compatible"]
    model_name: str
    runtime_mode: Literal["live", "fallback"]
    fallback_provider: Optional[Literal["mock"]] = None
    latency_ms: Optional[int] = None
    message: str


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


class ProjectCard(BaseModel):
    id: str
    name: str
    code: str
    summary: str
    status: str
    risk: str
    progress: int
    active_version: str
    blocked_items: int
    pending_approvals: int
    system_image_status: str


class VersionSummary(BaseModel):
    id: str
    name: str
    status: str
    branch_name: str
    us_total: int
    us_closed: int
    pending_runs: int
    pending_approvals: int


class USItem(BaseModel):
    id: str
    title: str
    owner: str
    status: str
    risk: str
    progress: int
    next_action: str


class AssetLane(BaseModel):
    id: str
    label: str
    status: str
    summary: str
    updated_at: str


class RunSummary(BaseModel):
    id: str
    status: str
    channel: Literal["web_runner"]
    title: str
    summary: str
    started_at: str


class RunDetail(RunSummary):
    timeline: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    failure_summary: str
    healing_status: str


class ApprovalSummary(BaseModel):
    id: str
    title: str
    status: str
    summary: str


class ApprovalDetail(ApprovalSummary):
    policy_reason: str
    conflict_fields: List[str] = Field(default_factory=list)
    recommended_resolution: str
    evidence: List[str] = Field(default_factory=list)


class ReleaseReadiness(BaseModel):
    version_id: str
    status: str
    score: int
    blockers: int
    approvals_open: int
    pending_merge: int
    execution_health: str
    summary: str
    blocker_items: List[str] = Field(default_factory=list)


class KnowledgeObject(BaseModel):
    id: str
    name: str
    type: str
    branch: str
    confidence: str
    relations: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    freshness: str


class DocumentationEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    body: str = Field(alias="copy", serialization_alias="copy")
    category: str


class AgentStep(BaseModel):
    id: str
    title: str
    status: Literal["pending", "running", "completed", "blocked"]
    phase: Optional[Literal["thinking", "acting", "observing", "deciding"]] = None
    reasoning: Optional[str] = None
    selected_tool_id: Optional[str] = None
    tool_invocation_id: Optional[str] = None
    observation_summary: Optional[str] = None
    decision: Optional[Literal["continue", "pause", "complete", "fail", "escalate"]] = None
    decision_rationale: Optional[str] = None
    next_plan_hint: Optional[str] = None


class AgentGoal(BaseModel):
    id: str
    conversation_id: str
    project_id: Optional[str] = None
    us_id: Optional[str] = None
    title: str
    status: Literal["draft", "pending", "running", "paused", "blocked", "completed", "failed", "cancelled"]
    summary: str
    steps: List[AgentStep]
    autonomy_level: Literal["full_auto", "semi_auto", "step_by_step"] = "semi_auto"
    max_steps: int = 50
    steps_completed: int = 0
    pause_reason: Optional[str] = None
    workflow_id: Optional[str] = None


class MessageBlock(BaseModel):
    type: Literal["text", "structured_card", "tool_progress"]
    text: str
    tone: Optional[str] = None


class ConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "system", "tool"]
    status: Literal["accepted", "streaming", "completed", "interrupted", "failed", "archived"] = "completed"
    content_type: Literal[
        "text",
        "markdown",
        "structured_card",
        "tool_progress",
        "thinking",
        "image_ref",
        "file_ref",
        "diff_ref",
        "approval_card",
        "conflict_card",
        "evidence_ref",
    ] = "text"
    created_at: str
    blocks: List[MessageBlock]
    tool_refs: List[str] = Field(default_factory=list)
    object_refs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    stream_id: Optional[str] = None
    sequence_max: Optional[int] = None


class ConversationSummaryCheckpoint(BaseModel):
    id: str
    conversation_id: str
    message_range_start: Optional[str] = None
    message_range_end: Optional[str] = None
    summary_text: str
    summary_object_refs: List[str] = Field(default_factory=list)
    summary_token_count: int = 0
    created_by: Literal["system", "user"] = "system"
    created_at: str


class ConversationLink(BaseModel):
    id: str
    left_conversation_id: str
    right_conversation_id: str
    link_kind: Literal["related", "duplicate", "merged_from", "derived_from"]
    reason: str
    confidence: float
    created_at: str


class SessionKnowledgeBinding(BaseModel):
    id: str
    conversation_id: str
    candidate_object_ref: str
    scope: Literal["session_only"] = "session_only"
    created_at: str


class ConversationSession(BaseModel):
    id: str
    session_id: str
    title: str
    space_type: SpaceType
    space_id: str
    project_id: Optional[str] = None
    version_id: Optional[str] = None
    us_id: Optional[str] = None
    task_id: Optional[str] = None
    initiator_id: Optional[str] = None
    status: Literal["draft", "active", "idle", "archived", "merged", "closed"] = "draft"
    last_message_at: Optional[str] = None
    latest_summary_checkpoint_id: Optional[str] = None
    merged_into_conversation_id: Optional[str] = None
    archived_at: Optional[str] = None
    messages: List[ConversationMessage] = Field(default_factory=list)
    agent_goals: List[AgentGoal] = Field(default_factory=list)
    related_conversation_ids: List[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    invocation_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    next_recommended_tools: List[str] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    active_projects: int
    running_versions: int
    blocked_items: int
    pending_approvals: int
    failed_runs: int
    projects: List[ProjectCard]


class BuildResponse(BaseModel):
    drafts: List[ProjectCard]
    imports_health: List[str]
    provider_health: str


class WelcomeResponse(BaseModel):
    recent_projects: List[ProjectCard]
    recent_versions: List[VersionSummary]
    recent_conversations: List[ConversationSession]


class ProjectWorkspaceResponse(BaseModel):
    project: ProjectCard
    versions: List[VersionSummary]
    current_version_id: str
    us_items: List[USItem]
    asset_lanes: List[AssetLane]
    runs: List[RunSummary]
    approvals: List[ApprovalSummary]


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    space_type: SpaceType
    space_id: str
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    version_id: Optional[str] = None
    us_id: Optional[str] = None
    task_id: Optional[str] = None
    initiator_id: Optional[str] = None


class ConversationMessageRequest(BaseModel):
    content: str
    client_message_id: Optional[str] = None


class ConversationArchiveRequest(BaseModel):
    archive: bool = True


class ConversationMergeRequest(BaseModel):
    target_conversation_id: str


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


class ToolInvocationRequest(BaseModel):
    conversation_id: Optional[str] = None
    tool_id: str
    input: Dict[str, Any] = Field(default_factory=dict)
    initiator_surface: Literal["chat", "ui", "api", "agent_loop"] = "ui"
    initiator_actor: Literal["user", "agent"] = "user"
    target_scope: Literal["central", "edge"] = "central"
    idempotency_key: Optional[str] = None


class AgentGoalCreateRequest(BaseModel):
    conversation_id: str
    title: str
    summary: str
    autonomy_level: Literal["full_auto", "semi_auto", "step_by_step"] = "semi_auto"
    project_id: Optional[str] = None
    us_id: Optional[str] = None
    steps: Optional[List[AgentStep]] = None


class AgentGoalFeedbackRequest(BaseModel):
    feedback: str


class EventPayload(BaseModel):
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    entity_version: int
    mutation_kind: Literal["replace", "patch", "append", "invalidate"]
    patch: Dict[str, Any] = Field(default_factory=dict)
    query_keys: List[List[str]] = Field(default_factory=list)
