from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..platform.tool_models import ToolInvocation


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


class AgentStep(BaseModel):
    id: str
    title: str
    status: Literal["pending", "running", "completed", "blocked"]
    phase: Optional[Literal["thinking", "acting", "observing", "deciding"]] = None
    reasoning: Optional[str] = None
    memory_context_hash: Optional[str] = None
    memory_context_summary: Optional[str] = None
    memory_recent_turn_count: int = 0
    memory_checkpoint_count: int = 0
    memory_retrieval_query: Optional[str] = None
    memory_retrieval_run_refs: List[str] = Field(default_factory=list)
    retrieved_context_refs: List[str] = Field(default_factory=list)
    retrieved_context_summary: Optional[str] = None
    available_tool_ids: List[str] = Field(default_factory=list)
    selected_tool_id: Optional[str] = None
    tool_input_payload: Dict[str, Any] = Field(default_factory=dict)
    tool_target_scope: Literal["central", "edge"] = "central"
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
    goal_template: Optional[str] = None
    goal_description: Optional[str] = None
    target_refs: List[str] = Field(default_factory=list)
    query_keys: List[List[str]] = Field(default_factory=list)
    planner_kind: Optional[str] = None
    planning_summary: Optional[str] = None
    title: str
    status: Literal["draft", "pending", "running", "paused", "blocked", "completed", "failed", "cancelled"]
    summary: str
    steps: List[AgentStep]
    autonomy_level: Literal["full_auto", "semi_auto", "step_by_step"] = "semi_auto"
    max_steps: int = Field(default=50, ge=1)
    max_model_calls: int = Field(default=32, ge=1)
    max_thinking_tokens: int = Field(default=500_000, ge=1)
    max_runtime_seconds: int = Field(default=1_800, ge=1)
    max_no_progress_observations: int = Field(default=3, ge=1)
    steps_completed: int = Field(default=0, ge=0)
    model_calls_used: int = Field(default=0, ge=0)
    thinking_input_tokens_used: int = Field(default=0, ge=0)
    thinking_output_tokens_used: int = Field(default=0, ge=0)
    thinking_tokens_used: int = Field(default=0, ge=0)
    no_progress_observations: int = Field(default=0, ge=0)
    started_at: Optional[str] = None
    last_progress_at: Optional[str] = None
    last_progress_fingerprint: Optional[str] = None
    budget_exhausted_reason: Optional[str] = None
    pause_reason: Optional[str] = None
    workflow_id: Optional[str] = None


class AgentMemoryItem(BaseModel):
    id: str
    memory_scope: Literal["working", "conversation", "project_long_term", "candidate"]
    owner_ref: str
    source_refs: List[str] = Field(default_factory=list)
    summary: str
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    status: Literal["active", "summarized", "expired"] = "active"
    expires_at: Optional[str] = None
    created_at: str


class AgentMemoryLink(BaseModel):
    id: str
    memory_id: str
    target_ref: str
    link_kind: Literal["derived_from", "supports", "mentions", "retrieved_for", "belongs_to", "evidenced_by"]
    confidence: float = Field(default=0, ge=0, le=1)
    created_at: str


class AgentWorkerAssignment(BaseModel):
    id: str
    swarm_run_id: str
    worker_agent_kind: Literal["context", "impact", "scenario", "case", "execution", "failure", "release"]
    target_refs: List[str] = Field(default_factory=list)
    input_context_refs: List[str] = Field(default_factory=list)
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    agent_goal_id: Optional[str] = None
    tool_invocation_refs: List[str] = Field(default_factory=list)
    candidate_result_ref: Optional[str] = None
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    confidence: float = Field(default=0, ge=0, le=1)
    summary: str = ""
    created_at: str
    completed_at: Optional[str] = None


class AgentSwarmRun(BaseModel):
    id: str
    parent_goal_id: str
    conversation_id: str
    swarm_kind: Literal["impact", "scenario", "case", "failure", "release", "ingestion"]
    status: Literal[
        "pending",
        "running",
        "merging",
        "completed",
        "partially_failed",
        "failed",
        "cancelled",
    ] = "pending"
    max_parallel_agents: int = Field(default=3, ge=1)
    budget_ref: Optional[str] = None
    merge_strategy: str = "confidence_weighted"
    target_refs: List[str] = Field(default_factory=list)
    result_summary: str = ""
    assignments: List[AgentWorkerAssignment] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None


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
    tool_invocations: List[ToolInvocation] = Field(default_factory=list)
    related_conversation_ids: List[str] = Field(default_factory=list)


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
    canonical_action_id: Optional[
        Literal["system-image.build-goal", "quality-loop.continue-goal"]
    ] = None


class ConversationArchiveRequest(BaseModel):
    archive: bool = True


class ConversationMergeRequest(BaseModel):
    target_conversation_id: str


class AgentGoalCreateRequest(BaseModel):
    conversation_id: str
    title: str
    summary: str
    autonomy_level: Literal["full_auto", "semi_auto", "step_by_step"] = "semi_auto"
    max_steps: int = Field(default=50, ge=1)
    max_model_calls: int = Field(default=32, ge=1)
    max_thinking_tokens: int = Field(default=500_000, ge=1)
    max_runtime_seconds: int = Field(default=1_800, ge=1)
    max_no_progress_observations: int = Field(default=3, ge=1)
    model_calls_used: int = Field(default=0, ge=0)
    thinking_input_tokens_used: int = Field(default=0, ge=0)
    thinking_output_tokens_used: int = Field(default=0, ge=0)
    project_id: Optional[str] = None
    us_id: Optional[str] = None
    goal_template: Optional[str] = None
    goal_description: Optional[str] = None
    target_refs: List[str] = Field(default_factory=list)
    query_keys: List[List[str]] = Field(default_factory=list)
    planner_kind: Optional[str] = None
    planning_summary: Optional[str] = None
    steps: Optional[List[AgentStep]] = None


class AgentGoalFeedbackRequest(BaseModel):
    feedback: str


class AgentGoalBudgetUpdateRequest(BaseModel):
    max_steps: Optional[int] = Field(default=None, ge=1)
    max_model_calls: Optional[int] = Field(default=None, ge=1)
    max_thinking_tokens: Optional[int] = Field(default=None, ge=1)
    max_runtime_seconds: Optional[int] = Field(default=None, ge=1)
    max_no_progress_observations: Optional[int] = Field(default=None, ge=1)


class AgentMemoryCheckpointRequest(BaseModel):
    conversation_id: Optional[str] = None
    agent_goal_id: Optional[str] = None
    space_ref: Optional[str] = None
    created_by: Literal["system", "user"] = "user"


class AgentSwarmCreateRequest(BaseModel):
    parent_goal_id: str
    swarm_kind: Literal["impact", "scenario", "case", "failure", "release", "ingestion"]
    target_refs: List[str] = Field(default_factory=list)
    max_parallel_agents: int = Field(default=3, ge=1)
    merge_strategy: str = "confidence_weighted"
    payload: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgentGoal",
    "AgentGoalBudgetUpdateRequest",
    "AgentGoalCreateRequest",
    "AgentGoalFeedbackRequest",
    "AgentMemoryCheckpointRequest",
    "AgentMemoryItem",
    "AgentMemoryLink",
    "AgentStep",
    "AgentSwarmCreateRequest",
    "AgentSwarmRun",
    "AgentWorkerAssignment",
    "ConversationArchiveRequest",
    "ConversationCreateRequest",
    "ConversationLink",
    "ConversationMergeRequest",
    "ConversationMessage",
    "ConversationMessageRequest",
    "ConversationSession",
    "ConversationSummaryCheckpoint",
    "MessageBlock",
    "SessionKnowledgeBinding",
    "SpaceType",
]
