from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .agent_models import (
    AgentGoal,
    AgentGoalCreateRequest,
    AgentMemoryItem,
    AgentMemoryLink,
    AgentSwarmRun,
    ConversationMessage,
    ConversationLink,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from ...domain.agent.memory import AgentMemoryContext
from ..platform.tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
)


@dataclass(frozen=True)
class AgentMemoryProjectSnapshot:
    id: str
    name: str
    progress: int
    risk: str
    blocked_items: int
    pending_approvals: int
    system_image_status: str


@dataclass(frozen=True)
class AgentMemoryVersionSnapshot:
    id: str
    name: str
    status: str
    us_closed: int
    us_total: int
    pending_runs: int
    pending_approvals: int


@dataclass(frozen=True)
class AgentMemoryAssetLaneSnapshot:
    label: str
    status: str
    summary: str


@dataclass(frozen=True)
class AgentMemoryUSSnapshot:
    id: str
    title: str
    owner: str
    status: str
    risk: str
    progress: int
    next_action: str
    asset_lanes: tuple[AgentMemoryAssetLaneSnapshot, ...]


@dataclass(frozen=True)
class AgentMemoryRunSnapshot:
    id: str
    title: str
    status: str
    channel: str
    summary: str


@dataclass(frozen=True)
class AgentMemoryApprovalSnapshot:
    id: str
    title: str
    status: str
    summary: str


class AgentMemoryStatePort(Protocol):
    """Durable memory facts and read-model snapshots consumed by Agent memory."""

    def get_goal(self, goal_id: str) -> AgentGoal:
        ...

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        ...

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    def list_conversations(self) -> Iterable[ConversationSession]:
        ...

    def available_tools(self) -> tuple[ToolDefinition, ...]:
        ...

    def list_summary_checkpoints(self) -> Iterable[ConversationSummaryCheckpoint]:
        ...

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        ...

    async def publish_memory_checkpointed(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        ...

    def persist_memory_item(self, item: AgentMemoryItem) -> None:
        ...

    def persist_memory_link(self, link: AgentMemoryLink) -> None:
        ...

    def list_memory_items(self) -> Iterable[AgentMemoryItem]:
        ...

    def session_candidate_refs(self, conversation_id: str) -> tuple[str, ...]:
        ...

    def candidate_overlay_refs(self, project_id: str) -> tuple[str, ...]:
        ...

    def project_snapshot(self, project_id: str) -> AgentMemoryProjectSnapshot | None:
        ...

    def latest_version_snapshot(self, project_id: str) -> AgentMemoryVersionSnapshot | None:
        ...

    def us_snapshot(self, us_id: str) -> AgentMemoryUSSnapshot | None:
        ...

    def recent_run_snapshots(self, project_id: str) -> tuple[AgentMemoryRunSnapshot, ...]:
        ...

    def recent_approval_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryApprovalSnapshot, ...]:
        ...


class AgentSwarmStatePort(Protocol):
    """Durable swarm projection and event effects used by the coordinator."""

    def get_swarm(self, swarm_id: str) -> AgentSwarmRun:
        ...

    def list_swarms(
        self,
        *,
        conversation_id: str | None = None,
        parent_goal_id: str | None = None,
    ) -> tuple[AgentSwarmRun, ...]:
        ...

    def persist_swarm(self, swarm: AgentSwarmRun) -> None:
        ...

    async def publish_swarm_event(
        self,
        swarm: AgentSwarmRun,
        event_type: str,
        patch: dict[str, Any],
    ) -> None:
        ...


class ConversationMessageStatePort(Protocol):
    """State and persistence required by the conversation message use case."""

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    def persist_message(
        self,
        conversation: ConversationSession,
        message: ConversationMessage,
    ) -> None:
        ...

    async def maybe_create_summary_checkpoint(
        self,
        conversation: ConversationSession,
    ) -> ConversationSummaryCheckpoint | None:
        ...


class ConversationSummaryStatePort(Protocol):
    """Checkpoint projection and persistence required by summary generation."""

    def list_summary_checkpoints(self) -> Iterable[ConversationSummaryCheckpoint]:
        ...

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        ...


class ConversationManagementStatePort(Protocol):
    """Conversation aggregate storage, access, and scope boundary."""

    def resolve_scope(
        self,
        space_type: str,
        space_id: str,
        *,
        project_id: str | None = None,
        version_id: str | None = None,
        us_id: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        ...

    def current_user_id(self) -> str:
        ...

    def require_project_access(self, project_id: str) -> None:
        ...

    def require_conversation_access(self, conversation: ConversationSession) -> None:
        ...

    def can_access_conversation(self, conversation: ConversationSession) -> bool:
        ...

    def find_conversation(
        self,
        *,
        space_type: str,
        space_id: str,
        owner_key: str,
    ) -> ConversationSession | None:
        ...

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    def list_conversations(self) -> Iterable[ConversationSession]:
        ...

    def persist_conversation(
        self,
        conversation: ConversationSession,
        *,
        lookup_key: tuple[str, str, str] | None = None,
    ) -> None:
        ...

    def persist_conversation_link(self, link: ConversationLink) -> None:
        ...

    def list_conversation_links(self) -> Iterable[ConversationLink]:
        ...


class AgentGoalProjectionStatePort(Protocol):
    """Persistence needed to project AgentGoal state into a conversation."""

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    def persist_goal_projection(
        self,
        conversation: ConversationSession,
        goal: AgentGoal,
    ) -> None:
        ...


class AgentGoalLifecycleStatePort(Protocol):
    """State, audit, message, and event effects for AgentGoal lifecycle rules."""

    def create_goal(self, goal: AgentGoal) -> None:
        ...

    def persist_goal(self, goal: AgentGoal) -> None:
        ...

    def has_goal(self, goal_id: str) -> bool:
        ...

    def get_goal(self, goal_id: str) -> AgentGoal:
        ...

    def list_goals_for_conversation(self, conversation_id: str) -> Iterable[AgentGoal]:
        ...

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        actor: str,
        actor_kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        ...

    async def publish_interrupted(self, goal: AgentGoal) -> None:
        ...

    async def publish_feedback(self, goal: AgentGoal, feedback: str) -> None:
        ...


class AgentLoopStatePort(Protocol):
    """Conversation and lifecycle effects required by the outer Agent loop."""

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    def create_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        ...

    def get_goal(self, goal_id: str) -> AgentGoal:
        ...

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def publish_goal_proposed(
        self,
        goal: AgentGoal,
        *,
        graph_kind: str,
    ) -> None:
        ...

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        ...


class AgentGraphStatePort(Protocol):
    """Durable facts and side effects required by Think/Act/Observe/Decide."""

    def get_goal(self, goal_id: str) -> AgentGoal:
        ...

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    async def create_tool_invocation(
        self,
        payload: ToolInvocationRequest,
    ) -> ToolInvocation:
        ...

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        ...

    def get_tool_invocation_or_none(
        self,
        invocation_id: str,
    ) -> ToolInvocation | None:
        ...

    def persist_goal(self, goal: AgentGoal) -> None:
        ...

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def publish_goal_event(
        self,
        goal: AgentGoal,
        event_type: str,
        patch: dict[str, Any],
    ) -> None:
        ...

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        tool_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
    ) -> ConversationMessage:
        ...

    async def create_memory_checkpoint(
        self,
        *,
        conversation_id: str,
        agent_goal_id: str,
    ) -> ConversationSummaryCheckpoint:
        ...

    def record_memory_item(
        self,
        *,
        memory_scope: str,
        owner_ref: str,
        summary: str,
        source_refs: list[str],
        object_refs: list[str],
        evidence_refs: list[str],
        link_refs: list[tuple[str, str, float]],
    ) -> AgentMemoryItem:
        ...

    async def build_memory_context(self, goal: AgentGoal) -> AgentMemoryContext:
        ...

    def available_tool_ids(self) -> tuple[str, ...]:
        ...


class AgentWorkflowStatePort(Protocol):
    """State synchronization required by Temporal workflow adapters."""

    def workflow_id_for_goal(self, goal_id: str) -> str | None:
        ...

    def accept_remote_goal(self, goal: AgentGoal) -> None:
        ...


class ConversationMessageRuntimePort(Protocol):
    """Cross-boundary commands required by main conversation orchestration."""

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        ...

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        ...

    async def plan_message(
        self,
        conversation: ConversationSession,
        content: str,
        *,
        canonical_action_id: str | None = None,
    ) -> Any:
        ...

    def fallback_text(self, conversation: ConversationSession) -> str:
        ...

    async def create_tool_invocation(self, request: Any) -> ToolInvocation:
        ...

    async def start_goal_from_proposal(
        self,
        conversation_id: str,
        proposal: Any,
    ) -> AgentGoal:
        ...

    def is_confirmation_message(self, content: str) -> bool:
        ...

    def list_tool_invocations(
        self,
        *,
        conversation_id: str,
        status: str,
    ) -> list[ToolInvocation]:
        ...

    def is_paused_goal(self, goal_id: str) -> bool:
        ...

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        ...

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        ...

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        ...

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        ...

    def project_goal(self, goal: AgentGoal) -> None:
        ...

    def record_source_binding_received(
        self,
        goal: AgentGoal,
        *,
        source_types: list[str],
    ) -> None:
        ...


class AgentConversationEventPublisherPort(Protocol):
    """Agent-owned event vocabulary exposed to conversation use cases."""

    async def publish_message_created(
        self,
        conversation_id: str,
        message: ConversationMessage,
    ) -> None:
        ...

    async def publish_summary_updated(
        self,
        conversation_id: str,
        checkpoint_id: str,
    ) -> None:
        ...


class AgentGoalExplanationQueryPort(Protocol):
    """Read-only facts needed to build an AgentGoal explanation."""

    def get_goal(self, goal_id: str) -> AgentGoal:
        ...

    def get_checkpoint(self, goal_id: str) -> Any:
        ...

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        ...

    def list_tool_invocations(self, *, agent_goal_id: str) -> list[ToolInvocation]:
        ...

    def list_agent_memory_items(self, *, source_ref: str) -> list[AgentMemoryItem]:
        ...

    def list_audit_events(self, *, agent_goal_id: str) -> list[AuditEvent]:
        ...


class AgentPlannerContextPort(Protocol):
    """Cross-domain read inputs exposed to the Agent planner."""

    async def memory_context(self, conversation: ConversationSession) -> AgentMemoryContext:
        ...

    def conversation_summary_fallback(self, conversation: ConversationSession) -> str:
        ...

    def quality_state(self, project_id: str | None, us_id: str | None) -> dict[str, str]:
        ...


class AgentPlanStatePort(Protocol):
    """Minimal system-image facts required by the AgentGoal plan compiler."""

    def project_exists(self, project_id: str) -> bool:
        ...

    def source_binding_incomplete(self, project_id: str) -> bool:
        ...

    def source_ingestion_statuses(self, project_id: str) -> tuple[str, ...]:
        ...

    def has_materialized_context(self, project_id: str) -> bool:
        ...

    def has_ready_official_baseline(self, project_id: str) -> bool:
        ...

    def known_tool_ids(self) -> frozenset[str]:
        ...


__all__ = [
    "AgentConversationEventPublisherPort",
    "AgentGraphStatePort",
    "AgentGoalLifecycleStatePort",
    "AgentGoalProjectionStatePort",
    "AgentGoalExplanationQueryPort",
    "AgentLoopStatePort",
    "AgentMemoryApprovalSnapshot",
    "AgentMemoryAssetLaneSnapshot",
    "AgentMemoryProjectSnapshot",
    "AgentMemoryRunSnapshot",
    "AgentMemoryStatePort",
    "AgentMemoryUSSnapshot",
    "AgentMemoryVersionSnapshot",
    "AgentSwarmStatePort",
    "AgentPlannerContextPort",
    "AgentPlanStatePort",
    "AgentWorkflowStatePort",
    "ConversationManagementStatePort",
    "ConversationMessageStatePort",
    "ConversationMessageRuntimePort",
    "ConversationSummaryStatePort",
]
