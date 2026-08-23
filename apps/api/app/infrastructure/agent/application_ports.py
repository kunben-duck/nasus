from __future__ import annotations

from typing import Any

from ...application.agent.agent_models import (
    AgentGoal,
    AgentGoalCreateRequest,
    AgentMemoryItem,
    AgentMemoryLink,
    AgentSwarmRun,
    ConversationLink,
    ConversationMessage,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from ...application.agent.ports import (
    AgentConversationEventPublisherPort,
    AgentGraphStatePort,
    AgentGoalLifecycleStatePort,
    AgentGoalProjectionStatePort,
    AgentGoalExplanationQueryPort,
    AgentLoopStatePort,
    AgentMemoryApprovalSnapshot,
    AgentMemoryProjectSnapshot,
    AgentMemoryRunSnapshot,
    AgentMemoryStatePort,
    AgentMemoryUSSnapshot,
    AgentMemoryVersionSnapshot,
    AgentSwarmStatePort,
    AgentPlannerContextPort,
    AgentPlanStatePort,
    AgentWorkflowStatePort,
    ConversationManagementStatePort,
    ConversationMessageRuntimePort,
    ConversationMessageStatePort,
    ConversationSummaryStatePort,
)
from ...application.platform.tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
)
from ...domain.agent.memory import AgentMemoryContext
from .application_port_dependencies import (
    AgentApplicationPersistenceAdapters,
    AgentApplicationProjectionState,
    AgentApplicationRuntimeAdapters,
)
from .conversation_management_dependencies import (
    AgentConversationManagementPersistenceAdapters,
    AgentConversationManagementProjectionState,
    AgentConversationManagementRuntimeAdapters,
)
from .conversation_runtime_dependencies import AgentConversationRuntimeAdapters
from .conversation_state_dependencies import (
    AgentConversationCheckpointAdapters,
    AgentConversationEventAdapters,
    AgentConversationPersistenceAdapters,
    AgentConversationProjectionState,
    AgentGoalExplanationAdapters,
)
from .goal_state_dependencies import (
    AgentGoalLifecycleAdapters,
    AgentGoalLifecycleState,
    AgentGoalProjectionPersistenceAdapters,
    AgentGoalProjectionState,
    AgentLoopRuntimeAdapters,
)
from .graph_state_dependencies import (
    AgentGraphLookupAdapters,
    AgentGraphMemoryAdapters,
    AgentGraphToolRuntimeAdapters,
)
from .memory_state_dependencies import (
    AgentMemoryCandidateProjectionState,
    AgentMemoryEventAdapters,
    AgentMemoryPersistenceAdapters,
    AgentMemoryProjectionState,
    AgentMemoryRuntimeAdapters,
    AgentMemoryWorkspaceProjectionState,
    CompatibilityAgentMemoryCandidateQueries,
    CompatibilityAgentMemoryWorkspaceQueries,
)
from .planning_dependencies import (
    AgentPlannerContextAdapters,
    AgentPlanningProjectionState,
    AgentPlanningRuntimeAdapters,
)
from .swarm_state_dependencies import (
    AgentSwarmEventAdapters,
    AgentSwarmPersistenceAdapters,
    AgentSwarmProjectionState,
)
from .workflow_state_dependencies import AgentWorkflowRuntimeAdapters


class LegacyConversationManagementStateAdapter(ConversationManagementStatePort):
    def __init__(
        self,
        state: AgentConversationManagementProjectionState,
        persistence: AgentConversationManagementPersistenceAdapters,
        runtime: AgentConversationManagementRuntimeAdapters,
    ) -> None:
        self._state = state
        self._persistence = persistence
        self._runtime = runtime

    def resolve_scope(
        self,
        space_type: str,
        space_id: str,
        *,
        project_id: str | None = None,
        version_id: str | None = None,
        us_id: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        return self._runtime.resolve_scope(
            space_type,
            space_id,
            project_id=project_id,
            version_id=version_id,
            us_id=us_id,
        )

    def current_user_id(self) -> str:
        return self._runtime.current_user_id()

    def require_project_access(self, project_id: str) -> None:
        self._runtime.require_project_access(project_id)

    def require_conversation_access(self, conversation: ConversationSession) -> None:
        self._runtime.require_conversation_access(conversation)

    def can_access_conversation(self, conversation: ConversationSession) -> bool:
        return self._runtime.can_access_conversation(conversation)

    def find_conversation(
        self,
        *,
        space_type: str,
        space_id: str,
        owner_key: str,
    ) -> ConversationSession | None:
        conversation_id = self._state.conversation_index.get(
            (space_type, space_id, owner_key)
        )
        if conversation_id is None:
            return None
        return self._state.conversations.get(conversation_id)

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._state.conversations[conversation_id]

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self._state.conversations.values())

    def persist_conversation(
        self,
        conversation: ConversationSession,
        *,
        lookup_key: tuple[str, str, str] | None = None,
    ) -> None:
        self._state.conversations[conversation.id] = conversation
        if lookup_key is not None:
            self._state.conversation_index[lookup_key] = conversation.id
        self._persistence.upsert_conversation(conversation)

    def persist_conversation_link(self, link: ConversationLink) -> None:
        self._state.conversation_links[link.id] = link
        self._persistence.upsert_conversation_link(link)

    def list_conversation_links(self) -> tuple[ConversationLink, ...]:
        return tuple(self._state.conversation_links.values())


class LegacyConversationMessageStateAdapter(ConversationMessageStatePort):
    def __init__(
        self,
        state: AgentConversationProjectionState,
        persistence: AgentConversationPersistenceAdapters,
        checkpoints: AgentConversationCheckpointAdapters,
    ) -> None:
        self._state = state
        self._persistence = persistence
        self._checkpoints = checkpoints

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._state.conversations[conversation_id]

    def persist_message(
        self,
        conversation: ConversationSession,
        message: ConversationMessage,
    ) -> None:
        self._persistence.append_message(conversation.id, message)
        self._persistence.upsert_conversation(conversation)

    async def maybe_create_summary_checkpoint(
        self,
        conversation: ConversationSession,
    ) -> ConversationSummaryCheckpoint | None:
        return await self._checkpoints.maybe_create_summary_checkpoint(
            conversation
        )


class LegacyAgentMemoryStateAdapter(AgentMemoryStatePort):
    """Maps the compatibility projections to the Agent memory application port."""

    def __init__(
        self,
        state: AgentMemoryProjectionState,
        persistence: AgentMemoryPersistenceAdapters,
        runtime: AgentMemoryRuntimeAdapters,
        events: AgentMemoryEventAdapters,
        candidates: CompatibilityAgentMemoryCandidateQueries,
        workspace: CompatibilityAgentMemoryWorkspaceQueries,
    ) -> None:
        self._state = state
        self._persistence = persistence
        self._runtime = runtime
        self._events = events
        self._candidates = candidates
        self._workspace = workspace

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._runtime.get_goal(goal_id)

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        return self._runtime.active_goal_for_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._state.conversations[conversation_id]

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self._state.conversations.values())

    def available_tools(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._runtime.available_tools())

    def list_summary_checkpoints(self) -> tuple[ConversationSummaryCheckpoint, ...]:
        return tuple(self._state.summary_checkpoints.values())

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        self._state.summary_checkpoints[checkpoint.id] = checkpoint
        conversation.latest_summary_checkpoint_id = checkpoint.id
        self._persistence.upsert_summary_checkpoint(checkpoint)
        self._persistence.upsert_conversation(conversation)

    async def publish_memory_checkpointed(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        await self._events.push_event(
            conversation.id,
            event_type="agent.memory.checkpointed",
            entity_type="conversation",
            entity_id=conversation.id,
            mutation_kind="patch",
            patch={"latest_summary_checkpoint_id": checkpoint.id},
            query_keys=[
                ["conversation", conversation.id],
                ["agent-memory", conversation.id],
            ],
        )

    def persist_memory_item(self, item: AgentMemoryItem) -> None:
        self._state.memory_items[item.id] = item
        self._persistence.upsert_memory_item(item)

    def persist_memory_link(self, link: AgentMemoryLink) -> None:
        self._state.memory_links[link.id] = link
        self._persistence.upsert_memory_link(link)

    def list_memory_items(self) -> tuple[AgentMemoryItem, ...]:
        return tuple(self._state.memory_items.values())

    def session_candidate_refs(self, conversation_id: str) -> tuple[str, ...]:
        return self._candidates.session_candidate_refs(conversation_id)

    def candidate_overlay_refs(self, project_id: str) -> tuple[str, ...]:
        return self._candidates.candidate_overlay_refs(project_id)

    def project_snapshot(self, project_id: str) -> AgentMemoryProjectSnapshot | None:
        return self._workspace.project_snapshot(project_id)

    def latest_version_snapshot(self, project_id: str) -> AgentMemoryVersionSnapshot | None:
        return self._workspace.latest_version_snapshot(project_id)

    def us_snapshot(self, us_id: str) -> AgentMemoryUSSnapshot | None:
        return self._workspace.us_snapshot(us_id)

    def recent_run_snapshots(self, project_id: str) -> tuple[AgentMemoryRunSnapshot, ...]:
        return self._workspace.recent_run_snapshots(project_id)

    def recent_approval_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryApprovalSnapshot, ...]:
        return self._workspace.recent_approval_snapshots(project_id)


class LegacyAgentSwarmStateAdapter(AgentSwarmStatePort):
    """Maps durable swarm facts and events to the compatibility runtime."""

    def __init__(
        self,
        state: AgentSwarmProjectionState,
        persistence: AgentSwarmPersistenceAdapters,
        events: AgentSwarmEventAdapters,
    ) -> None:
        self._state = state
        self._persistence = persistence
        self._events = events

    def get_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return self._state.swarms[swarm_id]

    def list_swarms(
        self,
        *,
        conversation_id: str | None = None,
        parent_goal_id: str | None = None,
    ) -> tuple[AgentSwarmRun, ...]:
        return tuple(
            swarm
            for swarm in sorted(self._state.swarms.values(), key=lambda item: (item.created_at, item.id))
            if (conversation_id is None or swarm.conversation_id == conversation_id)
            and (parent_goal_id is None or swarm.parent_goal_id == parent_goal_id)
        )

    def persist_swarm(self, swarm: AgentSwarmRun) -> None:
        self._state.swarms[swarm.id] = swarm
        self._persistence.upsert_swarm(swarm)

    async def publish_swarm_event(
        self,
        swarm: AgentSwarmRun,
        event_type: str,
        patch: dict[str, Any],
    ) -> None:
        event_patch = {
            **patch,
            "agent_goal_id": swarm.parent_goal_id,
            "swarm_run_id": swarm.id,
        }
        await self._events.push_event(
            swarm.conversation_id,
            event_type,
            "agent_swarm",
            swarm.id,
            "patch",
            event_patch,
            [
                ["conversation", swarm.conversation_id],
                ["agent-swarm", swarm.id],
                ["agent-swarms", swarm.conversation_id],
            ],
        )


class LegacyAgentGoalProjectionStateAdapter(AgentGoalProjectionStatePort):
    def __init__(
        self,
        state: AgentGoalProjectionState,
        persistence: AgentGoalProjectionPersistenceAdapters,
    ) -> None:
        self._state = state
        self._persistence = persistence

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._state.conversations[conversation_id]

    def persist_goal_projection(
        self,
        conversation: ConversationSession,
        goal: AgentGoal,
    ) -> None:
        self._persistence.upsert_goal(goal)
        self._persistence.upsert_conversation(conversation)


class LegacyAgentGoalLifecycleStateAdapter(AgentGoalLifecycleStatePort):
    def __init__(
        self,
        state: AgentGoalLifecycleState,
        adapters: AgentGoalLifecycleAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def create_goal(self, goal: AgentGoal) -> None:
        self._state.goals[goal.id] = goal
        self._adapters.project_goal(goal)

    def persist_goal(self, goal: AgentGoal) -> None:
        self._adapters.project_goal(goal)

    def has_goal(self, goal_id: str) -> bool:
        return goal_id in self._state.goals

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._state.goals[goal_id]

    def list_goals_for_conversation(
        self,
        conversation_id: str,
    ) -> tuple[AgentGoal, ...]:
        conversation = self._state.conversations[conversation_id]
        return tuple(conversation.agent_goals)

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
        self._adapters.record_goal_audit_event(
            goal,
            action=action,
            status=status,
            summary=summary,
            actor=actor,
            actor_kind=actor_kind,
            metadata=metadata,
        )

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        return await self._adapters.append_text_message(
            conversation_id,
            "assistant",
            text,
            metadata=metadata,
        )

    async def publish_interrupted(self, goal: AgentGoal) -> None:
        patch = {"status": "paused", "pause_reason": "user_interrupt"}
        await self._adapters.push_goal_event(
            goal.id,
            "agent.goal.updated",
            "patch",
            patch,
            [["agent-goal", goal.id], ["conversation", goal.conversation_id]],
        )

    async def publish_feedback(self, goal: AgentGoal, feedback: str) -> None:
        await self._adapters.push_goal_event(
            goal.id,
            "agent.goal.feedback",
            "patch",
            {"feedback": feedback},
            [["agent-goal", goal.id]],
        )


class LegacyAgentLoopStateAdapter(AgentLoopStatePort):
    def __init__(
        self,
        runtime: AgentLoopRuntimeAdapters,
        adapters: AgentGoalLifecycleAdapters,
    ) -> None:
        self._runtime = runtime
        self._adapters = adapters

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._runtime.get_conversation(conversation_id)

    def create_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        return self._runtime.create_goal(payload)

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._runtime.get_goal(goal_id)

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._adapters.record_goal_audit_event(
            goal,
            action=action,
            status=status,
            summary=summary,
            metadata=metadata,
        )

    async def publish_goal_proposed(
        self,
        goal: AgentGoal,
        *,
        graph_kind: str,
    ) -> None:
        await self._adapters.push_conversation_event(
            goal.conversation_id,
            "conversation.agent_goal.proposed",
            "agent_goal",
            goal.id,
            "append",
            {
                "goal_id": goal.id,
                "status": goal.status,
                "title": goal.title,
                "graph_kind": graph_kind,
            },
            [["conversation", goal.conversation_id]],
        )

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        return await self._adapters.append_text_message(
            conversation_id,
            "assistant",
            text,
            metadata=metadata,
        )


class LegacyAgentGraphStateAdapter(AgentGraphStatePort):
    def __init__(
        self,
        lookups: AgentGraphLookupAdapters,
        tools: AgentGraphToolRuntimeAdapters,
        memory: AgentGraphMemoryAdapters,
        goal_effects: AgentGoalLifecycleAdapters,
    ) -> None:
        self._lookups = lookups
        self._tools = tools
        self._memory = memory
        self._goal_effects = goal_effects

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._lookups.get_goal(goal_id)

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._lookups.get_conversation(conversation_id)

    async def create_tool_invocation(
        self,
        payload: ToolInvocationRequest,
    ) -> ToolInvocation:
        return await self._tools.create_tool_invocation(payload)

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return await self._tools.confirm_tool_invocation(invocation_id)

    def get_tool_invocation_or_none(
        self,
        invocation_id: str,
    ) -> ToolInvocation | None:
        try:
            return self._tools.get_tool_invocation(invocation_id)
        except KeyError:
            return None

    def persist_goal(self, goal: AgentGoal) -> None:
        self._goal_effects.project_goal(goal)

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._goal_effects.record_goal_audit_event(
            goal,
            action=action,
            status=status,
            summary=summary,
            metadata=metadata,
        )

    async def publish_goal_event(
        self,
        goal: AgentGoal,
        event_type: str,
        patch: dict[str, Any],
    ) -> None:
        query_keys: list[list[str]] = [
            ["conversation", goal.conversation_id],
            ["agent-goal", goal.id],
            ["agent-memory", goal.id],
        ]
        for query_key in getattr(goal, "query_keys", []):
            normalized_key = list(query_key)
            if normalized_key and normalized_key not in query_keys:
                query_keys.append(normalized_key)
        await self._goal_effects.push_goal_event(
            goal.id,
            event_type,
            "patch",
            patch,
            query_keys,
        )

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        tool_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
    ) -> ConversationMessage:
        return await self._goal_effects.append_text_message(
            conversation_id,
            "assistant",
            text,
            metadata=metadata,
            tool_refs=tool_refs,
            object_refs=object_refs,
        )

    async def create_memory_checkpoint(
        self,
        *,
        conversation_id: str,
        agent_goal_id: str,
    ) -> ConversationSummaryCheckpoint:
        return await self._memory.create_summary_checkpoint(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            created_by="system",
        )

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
        return self._memory.record_memory_item(
            memory_scope=memory_scope,
            owner_ref=owner_ref,
            summary=summary,
            source_refs=source_refs,
            object_refs=object_refs,
            evidence_refs=evidence_refs,
            link_refs=link_refs,
        )

    async def build_memory_context(self, goal: AgentGoal) -> AgentMemoryContext:
        conversation = self.get_conversation(goal.conversation_id)
        return await self._memory.build_memory_context(conversation)

    def available_tool_ids(self) -> tuple[str, ...]:
        return tuple(self._tools.available_tool_ids())


class LegacyAgentWorkflowStateAdapter(AgentWorkflowStatePort):
    def __init__(self, adapters: AgentWorkflowRuntimeAdapters) -> None:
        self._adapters = adapters

    def workflow_id_for_goal(self, goal_id: str) -> str | None:
        return self._adapters.get_goal(goal_id).workflow_id

    def accept_remote_goal(self, goal: AgentGoal) -> None:
        self._adapters.accept_remote_goal(goal)


class LegacyConversationMessageRuntimeAdapter(ConversationMessageRuntimePort):
    def __init__(self, adapters: AgentConversationRuntimeAdapters) -> None:
        self._adapters = adapters

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self._adapters.get_conversation(conversation_id)

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        return await self._adapters.append_message(
            conversation_id,
            role,
            text,
            metadata=metadata,
        )

    async def plan_message(
        self,
        conversation: ConversationSession,
        content: str,
        *,
        canonical_action_id: str | None = None,
    ):
        if canonical_action_id is not None:
            return await self._adapters.plan_message(
                conversation,
                content,
                canonical_action_id=canonical_action_id,
            )
        return await self._adapters.plan_message(conversation, content)

    def fallback_text(self, conversation: ConversationSession) -> str:
        return self._adapters.fallback_text(conversation)

    async def create_tool_invocation(self, request) -> ToolInvocation:
        return await self._adapters.create_tool_invocation(request)

    async def start_goal_from_proposal(
        self,
        conversation_id: str,
        proposal,
    ) -> AgentGoal:
        return await self._adapters.start_goal_from_proposal(
            conversation_id,
            proposal,
        )

    def is_confirmation_message(self, content: str) -> bool:
        return self._adapters.is_confirmation_message(content)

    def list_tool_invocations(
        self,
        *,
        conversation_id: str,
        status: str,
    ) -> list[ToolInvocation]:
        return self._adapters.list_tool_invocations(
            conversation_id=conversation_id,
            status=status,
        )

    def is_paused_goal(self, goal_id: str) -> bool:
        return self._adapters.is_paused_goal(goal_id)

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        return await self._adapters.resume_goal(goal_id)

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return self._adapters.get_tool_invocation(invocation_id)

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return await self._adapters.confirm_tool_invocation(
            invocation_id
        )

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        return self._adapters.active_goal_for_conversation(conversation_id)

    def project_goal(self, goal: AgentGoal) -> None:
        self._adapters.project_goal(goal)

    def record_source_binding_received(
        self,
        goal: AgentGoal,
        *,
        source_types: list[str],
    ) -> None:
        self._adapters.record_source_binding_received(goal, source_types)


class LegacyConversationSummaryStateAdapter(ConversationSummaryStatePort):
    def __init__(
        self,
        state: AgentConversationProjectionState,
        persistence: AgentConversationPersistenceAdapters,
    ) -> None:
        self._state = state
        self._persistence = persistence

    def list_summary_checkpoints(self) -> tuple[ConversationSummaryCheckpoint, ...]:
        return tuple(self._state.summary_checkpoints.values())

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        self._state.summary_checkpoints[checkpoint.id] = checkpoint
        self._persistence.upsert_summary_checkpoint(checkpoint)
        self._persistence.upsert_conversation(conversation)


class LegacyAgentConversationEventPublisher(AgentConversationEventPublisherPort):
    def __init__(self, adapters: AgentConversationEventAdapters) -> None:
        self._adapters = adapters

    async def publish_message_created(
        self,
        conversation_id: str,
        message: ConversationMessage,
    ) -> None:
        await self._adapters.push_event(
            conversation_id,
            event_type="conversation.message.created",
            entity_type="conversation",
            entity_id=conversation_id,
            mutation_kind="patch",
            patch={"message_id": message.id},
            query_keys=[["conversation", conversation_id]],
            payload={"message_id": message.id, "message": message.model_dump()},
        )

    async def publish_summary_updated(
        self,
        conversation_id: str,
        checkpoint_id: str,
    ) -> None:
        await self._adapters.push_event(
            conversation_id,
            event_type="conversation.summary.updated",
            entity_type="conversation",
            entity_id=conversation_id,
            mutation_kind="patch",
            patch={"latest_summary_checkpoint_id": checkpoint_id},
            query_keys=[["conversation", conversation_id]],
        )


class LegacyAgentGoalExplanationQueryAdapter(AgentGoalExplanationQueryPort):
    def __init__(self, adapters: AgentGoalExplanationAdapters) -> None:
        self._adapters = adapters

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._adapters.get_goal(goal_id)

    def get_checkpoint(self, goal_id: str):
        return self._adapters.get_checkpoint(goal_id)

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return self._adapters.get_tool_invocation(invocation_id)

    def list_tool_invocations(self, *, agent_goal_id: str) -> list[ToolInvocation]:
        return self._adapters.list_tool_invocations(
            agent_goal_id=agent_goal_id
        )

    def list_agent_memory_items(self, *, source_ref: str) -> list[AgentMemoryItem]:
        return self._adapters.list_agent_memory_items(source_ref=source_ref)

    def list_audit_events(self, *, agent_goal_id: str) -> list[AuditEvent]:
        return self._adapters.list_audit_events(agent_goal_id=agent_goal_id)


class LegacyAgentPlannerContextAdapter(AgentPlannerContextPort):
    def __init__(self, adapters: AgentPlannerContextAdapters) -> None:
        self._adapters = adapters

    async def memory_context(self, conversation: ConversationSession) -> AgentMemoryContext:
        return await self._adapters.memory_context(conversation)

    def conversation_summary_fallback(self, conversation: ConversationSession) -> str:
        return self._adapters.conversation_summary_fallback(conversation)

    def quality_state(self, project_id: str | None, us_id: str | None) -> dict[str, str]:
        return self._adapters.quality_state(
            project_id,
            us_id,
        )


class LegacyAgentPlanStateAdapter(AgentPlanStatePort):
    def __init__(
        self,
        state: AgentPlanningProjectionState,
        adapters: AgentPlanningRuntimeAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def project_exists(self, project_id: str) -> bool:
        return project_id in self._state.projects

    def source_binding_incomplete(self, project_id: str) -> bool:
        return self._adapters.source_binding_incomplete(project_id)

    def source_ingestion_statuses(self, project_id: str) -> tuple[str, ...]:
        return tuple(
            source.ingestion_status
            for source in self._state.raw_assets.get(project_id, [])
        )

    def has_materialized_context(self, project_id: str) -> bool:
        return (
            bool(self._state.knowledge_objects.get(project_id))
            and bool(self._state.context_relationships.get(project_id))
            and bool(self._state.quality_metric_snapshots.get(project_id))
        )

    def has_ready_official_baseline(self, project_id: str) -> bool:
        return any(
            baseline.kind == "official" and baseline.status == "ready"
            for baseline in self._state.baselines.get(project_id, [])
        )

    def known_tool_ids(self) -> frozenset[str]:
        return self._adapters.known_tool_ids()


class LegacyAgentApplicationPorts:
    """Anti-corruption boundary while the compatibility store is retired."""

    def __init__(
        self,
        state: AgentApplicationProjectionState,
        persistence: AgentApplicationPersistenceAdapters,
        runtime: AgentApplicationRuntimeAdapters,
    ) -> None:
        conversation_management_state = (
            AgentConversationManagementProjectionState(
                conversations=state.conversations,
                conversation_index=state.conversation_index,
                conversation_links=state.conversation_links,
            )
        )
        conversation_management_persistence = (
            AgentConversationManagementPersistenceAdapters(
                upsert_conversation=persistence.upsert_conversation,
                upsert_conversation_link=persistence.upsert_conversation_link,
            )
        )
        conversation_state = AgentConversationProjectionState(
            conversations=state.conversations,
            summary_checkpoints=state.conversation_summary_checkpoints,
        )
        conversation_persistence = AgentConversationPersistenceAdapters(
            append_message=persistence.append_message,
            upsert_conversation=persistence.upsert_conversation,
            upsert_summary_checkpoint=persistence.upsert_summary_checkpoint,
        )
        goal_projection_state = AgentGoalProjectionState(
            conversations=state.conversations,
        )
        goal_lifecycle_state = AgentGoalLifecycleState(
            goals=state.agent_goals,
            conversations=state.conversations,
        )
        memory_projection_state = AgentMemoryProjectionState(
            conversations=state.conversations,
            summary_checkpoints=state.conversation_summary_checkpoints,
            memory_items=state.agent_memory_items,
            memory_links=state.agent_memory_links,
        )
        memory_persistence = AgentMemoryPersistenceAdapters(
            upsert_summary_checkpoint=persistence.upsert_summary_checkpoint,
            upsert_conversation=persistence.upsert_conversation,
            upsert_memory_item=persistence.upsert_memory_item,
            upsert_memory_link=persistence.upsert_memory_link,
        )
        memory_candidates = CompatibilityAgentMemoryCandidateQueries(
            AgentMemoryCandidateProjectionState(
                session_knowledge_bindings=state.session_knowledge_bindings,
                context_object_overlays=state.context_object_overlays,
            )
        )
        memory_workspace = CompatibilityAgentMemoryWorkspaceQueries(
            AgentMemoryWorkspaceProjectionState(
                projects=state.projects,
                versions=state.versions,
                us_items=state.us_items,
                asset_lanes=state.asset_lanes,
                runs=state.runs,
                approvals=state.approvals,
            )
        )
        swarm_projection_state = AgentSwarmProjectionState(
            swarms=state.agent_swarms,
        )
        swarm_persistence = AgentSwarmPersistenceAdapters(
            upsert_swarm=persistence.upsert_swarm,
        )
        goal_projection_persistence = AgentGoalProjectionPersistenceAdapters(
            upsert_goal=persistence.upsert_goal,
            upsert_conversation=persistence.upsert_conversation,
        )
        goal_lifecycle_adapters = AgentGoalLifecycleAdapters(
            project_goal=runtime.project_goal,
            record_goal_audit_event=runtime.record_goal_audit_event,
            append_text_message=runtime.append_text_message,
            push_goal_event=runtime.push_goal_event,
            push_conversation_event=runtime.push_conversation_event,
        )
        self.conversation_management = LegacyConversationManagementStateAdapter(
            conversation_management_state,
            conversation_management_persistence,
            AgentConversationManagementRuntimeAdapters(
                resolve_scope=runtime.resolve_conversation_scope,
                current_user_id=runtime.current_user_id,
                require_project_access=runtime.require_project_access,
                require_conversation_access=runtime.require_conversation_access,
                can_access_conversation=runtime.can_access_conversation,
            ),
        )
        self.conversation_messages = LegacyConversationMessageStateAdapter(
            conversation_state,
            conversation_persistence,
            AgentConversationCheckpointAdapters(
                maybe_create_summary_checkpoint=runtime.maybe_create_summary_checkpoint,
            ),
        )

        def record_source_binding_received(goal: AgentGoal, source_types: list[str]) -> Any:
            return runtime.record_goal_audit_event(
                goal,
                action="agent.goal.source_binding_received",
                status=goal.status,
                summary=f"Source bindings received for AgentGoal: {goal.title}",
                actor=runtime.current_user_id(),
                actor_kind="user",
                metadata={"source_types": source_types},
            )

        self.conversation_runtime = LegacyConversationMessageRuntimeAdapter(
            AgentConversationRuntimeAdapters(
                get_conversation=runtime.get_conversation,
                append_message=runtime.append_text_message,
                plan_message=runtime.plan_message,
                fallback_text=runtime.conversation_summary_fallback,
                create_tool_invocation=runtime.create_tool_invocation,
                start_goal_from_proposal=runtime.start_goal_from_proposal,
                is_confirmation_message=runtime.is_confirmation_message,
                list_tool_invocations=runtime.list_tool_invocations,
                is_paused_goal=runtime.is_paused_goal,
                resume_goal=runtime.resume_goal,
                get_tool_invocation=runtime.get_tool_invocation,
                confirm_tool_invocation=runtime.confirm_tool_invocation,
                active_goal_for_conversation=runtime.active_goal_for_conversation,
                project_goal=runtime.project_goal,
                record_source_binding_received=record_source_binding_received,
            )
        )
        self.conversation_summaries = LegacyConversationSummaryStateAdapter(
            conversation_state,
            conversation_persistence,
        )
        self.events = LegacyAgentConversationEventPublisher(
            AgentConversationEventAdapters(
                push_event=runtime.push_conversation_event,
            )
        )
        self.graph_state = LegacyAgentGraphStateAdapter(
            AgentGraphLookupAdapters(
                get_goal=runtime.get_goal,
                get_conversation=runtime.get_conversation,
            ),
            AgentGraphToolRuntimeAdapters(
                create_tool_invocation=runtime.create_tool_invocation,
                confirm_tool_invocation=runtime.confirm_tool_invocation,
                get_tool_invocation=runtime.get_tool_invocation,
                available_tool_ids=lambda: (tool.tool_id for tool in state.tools),
            ),
            AgentGraphMemoryAdapters(
                create_summary_checkpoint=runtime.create_summary_checkpoint,
                record_memory_item=runtime.record_memory_item,
                build_memory_context=lambda conversation: runtime.build_memory_context(
                    conversation,
                    trace_retrieval=True,
                ),
            ),
            goal_lifecycle_adapters,
        )
        self.goal_lifecycle = LegacyAgentGoalLifecycleStateAdapter(
            goal_lifecycle_state,
            goal_lifecycle_adapters,
        )
        self.goal_projection = LegacyAgentGoalProjectionStateAdapter(
            goal_projection_state,
            goal_projection_persistence,
        )
        self.goal_explanations = LegacyAgentGoalExplanationQueryAdapter(
            AgentGoalExplanationAdapters(
                get_goal=runtime.get_goal,
                get_checkpoint=runtime.get_checkpoint,
                get_tool_invocation=runtime.get_tool_invocation,
                list_tool_invocations=runtime.list_tool_invocations,
                list_agent_memory_items=runtime.list_agent_memory_items,
                list_audit_events=runtime.list_audit_events,
            )
        )
        self.loop_state = LegacyAgentLoopStateAdapter(
            AgentLoopRuntimeAdapters(
                get_conversation=runtime.get_conversation,
                create_goal=runtime.create_goal_record,
                get_goal=runtime.get_goal,
            ),
            goal_lifecycle_adapters,
        )
        self.memory_state = LegacyAgentMemoryStateAdapter(
            memory_projection_state,
            memory_persistence,
            AgentMemoryRuntimeAdapters(
                get_goal=runtime.get_goal,
                active_goal_for_conversation=runtime.active_goal_for_conversation,
                available_tools=lambda: tuple(state.tools),
            ),
            AgentMemoryEventAdapters(
                push_event=runtime.push_conversation_event,
            ),
            memory_candidates,
            memory_workspace,
        )
        self.swarm_state = LegacyAgentSwarmStateAdapter(
            swarm_projection_state,
            swarm_persistence,
            AgentSwarmEventAdapters(
                push_event=runtime.push_conversation_event,
            ),
        )
        self.planner_context = LegacyAgentPlannerContextAdapter(
            AgentPlannerContextAdapters(
                memory_context=lambda conversation: runtime.build_memory_context(
                    conversation,
                    trace_retrieval=True,
                ),
                conversation_summary_fallback=runtime.conversation_summary_fallback,
                quality_state=runtime.quality_state,
            )
        )
        self.plan_state = LegacyAgentPlanStateAdapter(
            AgentPlanningProjectionState(
                projects=state.projects,
                raw_assets=state.raw_assets,
                knowledge_objects=state.knowledge_objects,
                context_relationships=state.context_relationships,
                quality_metric_snapshots=state.quality_metric_snapshots,
                baselines=state.baselines,
            ),
            AgentPlanningRuntimeAdapters(
                source_binding_incomplete=runtime.source_binding_incomplete,
                known_tool_ids=lambda: frozenset(
                    tool.tool_id for tool in state.tools
                ),
            ),
        )
        self.workflow_state = LegacyAgentWorkflowStateAdapter(
            AgentWorkflowRuntimeAdapters(
                get_goal=runtime.get_goal,
                accept_remote_goal=runtime.accept_remote_goal,
            )
        )


# Neutral names are used by durable composition. The legacy names remain as
# compatibility exports for migration tests and third-party extensions.
DelegatingAgentConversationEventPublisher = LegacyAgentConversationEventPublisher
DelegatingAgentGoalExplanationQueryAdapter = LegacyAgentGoalExplanationQueryAdapter
DelegatingAgentGraphStateAdapter = LegacyAgentGraphStateAdapter
DelegatingAgentLoopStateAdapter = LegacyAgentLoopStateAdapter
DelegatingAgentPlannerContextAdapter = LegacyAgentPlannerContextAdapter
DelegatingAgentWorkflowStateAdapter = LegacyAgentWorkflowStateAdapter
DelegatingConversationMessageRuntimeAdapter = LegacyConversationMessageRuntimeAdapter


__all__ = [
    "DelegatingAgentConversationEventPublisher",
    "DelegatingAgentGoalExplanationQueryAdapter",
    "DelegatingAgentGraphStateAdapter",
    "DelegatingAgentLoopStateAdapter",
    "DelegatingAgentPlannerContextAdapter",
    "DelegatingAgentWorkflowStateAdapter",
    "DelegatingConversationMessageRuntimeAdapter",
    "LegacyAgentApplicationPorts",
]
