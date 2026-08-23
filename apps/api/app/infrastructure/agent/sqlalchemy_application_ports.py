from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...application.agent.agent_models import (
    AgentGoal,
    AgentMemoryItem,
    AgentMemoryLink,
    AgentSwarmRun,
    ConversationLink,
    ConversationMessage,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from ...application.agent.lifecycle import ACTIVE_GOAL_STATUSES
from ...application.agent.ports import (
    AgentGoalLifecycleStatePort,
    AgentGoalProjectionStatePort,
    AgentMemoryApprovalSnapshot,
    AgentMemoryAssetLaneSnapshot,
    AgentMemoryProjectSnapshot,
    AgentMemoryRunSnapshot,
    AgentMemoryStatePort,
    AgentMemoryUSSnapshot,
    AgentMemoryVersionSnapshot,
    AgentPlanStatePort,
    AgentSwarmStatePort,
    ConversationManagementStatePort,
    ConversationMessageStatePort,
    ConversationSummaryStatePort,
)
from ...application.platform.tool_models import ToolDefinition
from ..persistence.conversation_repository import ConversationRepository
from ..persistence.project_repository import ProjectRepository
from ..persistence.quality_loop_repository import QualityLoopRepository
from ..persistence.system_image_repository import SystemImageRepository
from .application_port_dependencies import AgentApplicationRuntimeAdapters
from .application_ports import (
    DelegatingAgentConversationEventPublisher,
    DelegatingAgentGoalExplanationQueryAdapter,
    DelegatingAgentGraphStateAdapter,
    DelegatingAgentLoopStateAdapter,
    DelegatingAgentPlannerContextAdapter,
    DelegatingConversationMessageRuntimeAdapter,
)
from .conversation_management_dependencies import (
    AgentConversationManagementRuntimeAdapters,
)
from .conversation_runtime_dependencies import AgentConversationRuntimeAdapters
from .conversation_state_dependencies import (
    AgentConversationCheckpointAdapters,
    AgentConversationEventAdapters,
    AgentGoalExplanationAdapters,
)
from .goal_state_dependencies import (
    AgentGoalLifecycleAdapters,
    AgentLoopRuntimeAdapters,
)
from .graph_state_dependencies import (
    AgentGraphLookupAdapters,
    AgentGraphMemoryAdapters,
    AgentGraphToolRuntimeAdapters,
)
from .planning_dependencies import AgentPlannerContextAdapters


def _required(value: Any | None, entity: str, entity_id: str) -> Any:
    if value is None:
        raise KeyError(f"{entity} {entity_id} was not found")
    return value


class SQLAlchemyConversationManagementState(ConversationManagementStatePort):
    def __init__(
        self,
        repository: ConversationRepository,
        runtime: AgentConversationManagementRuntimeAdapters,
    ) -> None:
        self._repository = repository
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
        if owner_key.startswith("project:"):
            conversation = self._repository.find_conversation(
                space_type=space_type,
                space_id=space_id,
                project_id=owner_key.removeprefix("project:"),
            )
        elif owner_key.startswith("user:"):
            conversation = self._repository.find_conversation(
                space_type=space_type,
                space_id=space_id,
                initiator_id=owner_key.removeprefix("user:"),
            )
        else:
            conversation = None
        return conversation

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        conversation = _required(
            self._repository.get_conversation(conversation_id),
            "Conversation",
            conversation_id,
        )
        return conversation

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self._repository.load_all())

    def persist_conversation(
        self,
        conversation: ConversationSession,
        *,
        lookup_key: tuple[str, str, str] | None = None,
    ) -> None:
        del lookup_key
        self._repository.upsert_conversation(conversation)

    def persist_conversation_link(self, link: ConversationLink) -> None:
        self._repository.upsert_conversation_link(link)

    def list_conversation_links(self) -> tuple[ConversationLink, ...]:
        return tuple(self._repository.load_conversation_links())


class SQLAlchemyConversationMessageState(ConversationMessageStatePort):
    def __init__(
        self,
        repository: ConversationRepository,
        checkpoints: AgentConversationCheckpointAdapters,
    ) -> None:
        self._repository = repository
        self._checkpoints = checkpoints

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        conversation = _required(
            self._repository.get_conversation(conversation_id),
            "Conversation",
            conversation_id,
        )
        return conversation

    def persist_message(
        self,
        conversation: ConversationSession,
        message: ConversationMessage,
    ) -> None:
        self._repository.append_message(conversation.id, message)
        self._repository.upsert_conversation(conversation)

    async def maybe_create_summary_checkpoint(
        self,
        conversation: ConversationSession,
    ) -> ConversationSummaryCheckpoint | None:
        return await self._checkpoints.maybe_create_summary_checkpoint(conversation)


class SQLAlchemyConversationSummaryState(ConversationSummaryStatePort):
    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def list_summary_checkpoints(self) -> tuple[ConversationSummaryCheckpoint, ...]:
        return tuple(self._repository.load_summary_checkpoints())

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        self._repository.upsert_summary_checkpoint(checkpoint)
        self._repository.upsert_conversation(conversation)


class SQLAlchemyAgentGoalProjectionState(AgentGoalProjectionStatePort):
    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        conversation = _required(
            self._repository.get_conversation(conversation_id),
            "Conversation",
            conversation_id,
        )
        return conversation

    def persist_goal_projection(
        self,
        conversation: ConversationSession,
        goal: AgentGoal,
    ) -> None:
        self._repository.upsert_goal(goal)
        self._repository.upsert_conversation(conversation)


class SQLAlchemyAgentGoalLifecycleState(AgentGoalLifecycleStatePort):
    def __init__(
        self,
        repository: ConversationRepository,
        effects: AgentGoalLifecycleAdapters,
    ) -> None:
        self._repository = repository
        self._effects = effects

    def create_goal(self, goal: AgentGoal) -> None:
        self._repository.upsert_goal(goal)

    def persist_goal(self, goal: AgentGoal) -> None:
        self._repository.upsert_goal(goal)

    def has_goal(self, goal_id: str) -> bool:
        return self._repository.get_agent_goal(goal_id) is not None

    def get_goal(self, goal_id: str) -> AgentGoal:
        goal = _required(
            self._repository.get_agent_goal(goal_id),
            "AgentGoal",
            goal_id,
        )
        return goal

    def list_goals_for_conversation(
        self,
        conversation_id: str,
    ) -> tuple[AgentGoal, ...]:
        return tuple(
            self._repository.list_agent_goals(conversation_id=conversation_id)
        )

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
        self._effects.record_goal_audit_event(
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
        return await self._effects.append_text_message(
            conversation_id,
            "assistant",
            text,
            metadata=metadata,
        )

    async def publish_interrupted(self, goal: AgentGoal) -> None:
        patch = {"status": "paused", "pause_reason": "user_interrupt"}
        await self._effects.push_goal_event(
            goal.id,
            "agent.goal.updated",
            "patch",
            patch,
            [["agent-goal", goal.id], ["conversation", goal.conversation_id]],
        )

    async def publish_feedback(self, goal: AgentGoal, feedback: str) -> None:
        await self._effects.push_goal_event(
            goal.id,
            "agent.goal.feedback",
            "patch",
            {"feedback": feedback},
            [["agent-goal", goal.id]],
        )


class SQLAlchemyAgentMemoryState(AgentMemoryStatePort):
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        quality_loop: QualityLoopRepository,
        system_image: SystemImageRepository,
        tools: Sequence[ToolDefinition],
        push_event: Any,
    ) -> None:
        self._conversations = conversations
        self._projects = projects
        self._quality_loop = quality_loop
        self._system_image = system_image
        self._tools = tuple(tools)
        self._push_event = push_event

    def get_goal(self, goal_id: str) -> AgentGoal:
        goal = _required(
            self._conversations.get_agent_goal(goal_id),
            "AgentGoal",
            goal_id,
        )
        return goal

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        goals = self._conversations.list_agent_goals(
            conversation_id=conversation_id
        )
        return next(
            (goal for goal in reversed(goals) if goal.status in ACTIVE_GOAL_STATUSES),
            None,
        )

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        conversation = _required(
            self._conversations.get_conversation(conversation_id),
            "Conversation",
            conversation_id,
        )
        return conversation

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self._conversations.load_all())

    def available_tools(self) -> tuple[ToolDefinition, ...]:
        return self._tools

    def list_summary_checkpoints(self) -> tuple[ConversationSummaryCheckpoint, ...]:
        return tuple(self._conversations.load_summary_checkpoints())

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        conversation.latest_summary_checkpoint_id = checkpoint.id
        self._conversations.upsert_summary_checkpoint(checkpoint)
        self._conversations.upsert_conversation(conversation)

    async def publish_memory_checkpointed(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        await self._push_event(
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
        self._conversations.upsert_agent_memory_item(item)

    def persist_memory_link(self, link: AgentMemoryLink) -> None:
        self._conversations.upsert_agent_memory_link(link)

    def list_memory_items(self) -> tuple[AgentMemoryItem, ...]:
        return tuple(self._conversations.load_agent_memory_items())

    def session_candidate_refs(self, conversation_id: str) -> tuple[str, ...]:
        return tuple(
            binding.candidate_object_ref
            for binding in self._conversations.load_session_knowledge_bindings()
            if binding.conversation_id == conversation_id
        )

    def candidate_overlay_refs(self, project_id: str) -> tuple[str, ...]:
        return tuple(
            f"context_overlay:{overlay.id}:{overlay.status}"
            for overlay in self._system_image.load_project_snapshot(project_id).overlays
            if overlay.status == "candidate"
        )

    def project_snapshot(self, project_id: str) -> AgentMemoryProjectSnapshot | None:
        project = self._projects.get_project(project_id)
        if project is None:
            return None
        return AgentMemoryProjectSnapshot(
            id=project.id,
            name=project.name,
            progress=project.progress,
            risk=project.risk,
            blocked_items=project.blocked_items,
            pending_approvals=project.pending_approvals,
            system_image_status=project.system_image_status,
        )

    def latest_version_snapshot(
        self,
        project_id: str,
    ) -> AgentMemoryVersionSnapshot | None:
        versions = self._projects.list_versions(project_id)
        if not versions:
            return None
        version = versions[0]
        return AgentMemoryVersionSnapshot(
            id=version.id,
            name=version.name,
            status=version.status,
            us_closed=version.us_closed,
            us_total=version.us_total,
            pending_runs=version.pending_runs,
            pending_approvals=version.pending_approvals,
        )

    def us_snapshot(self, us_id: str) -> AgentMemoryUSSnapshot | None:
        us_item = self._quality_loop.get_us_item(us_id)
        if us_item is None:
            return None
        return AgentMemoryUSSnapshot(
            id=us_item.id,
            title=us_item.title,
            owner=us_item.owner,
            status=us_item.status,
            risk=us_item.risk,
            progress=us_item.progress,
            next_action=us_item.next_action,
            asset_lanes=tuple(
                AgentMemoryAssetLaneSnapshot(
                    label=lane.label,
                    status=lane.status,
                    summary=lane.summary,
                )
                for lane in self._quality_loop.list_asset_lanes_for_us(us_id)
            ),
        )

    def recent_run_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryRunSnapshot, ...]:
        return tuple(
            AgentMemoryRunSnapshot(
                id=run.id,
                title=run.title,
                status=run.status,
                channel=run.channel,
                summary=run.summary,
            )
            for run in self._quality_loop.list_runs(project_id)[:3]
        )

    def recent_approval_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryApprovalSnapshot, ...]:
        return tuple(
            AgentMemoryApprovalSnapshot(
                id=approval.id,
                title=approval.title,
                status=approval.status,
                summary=approval.summary,
            )
            for approval in self._quality_loop.list_approvals(project_id)[:3]
        )


class SQLAlchemyAgentSwarmState(AgentSwarmStatePort):
    def __init__(
        self,
        repository: ConversationRepository,
        push_event: Any,
    ) -> None:
        self._repository = repository
        self._push_event = push_event

    def get_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return _required(
            self._repository.get_agent_swarm(swarm_id),
            "AgentSwarmRun",
            swarm_id,
        )

    def list_swarms(
        self,
        *,
        conversation_id: str | None = None,
        parent_goal_id: str | None = None,
    ) -> tuple[AgentSwarmRun, ...]:
        return tuple(
            self._repository.list_agent_swarms(
                conversation_id=conversation_id,
                parent_goal_id=parent_goal_id,
            )
        )

    def persist_swarm(self, swarm: AgentSwarmRun) -> None:
        self._repository.upsert_agent_swarm(swarm)

    async def publish_swarm_event(
        self,
        swarm: AgentSwarmRun,
        event_type: str,
        patch: dict[str, Any],
    ) -> None:
        await self._push_event(
            swarm.conversation_id,
            event_type,
            "agent_swarm",
            swarm.id,
            "patch",
            {
                **patch,
                "agent_goal_id": swarm.parent_goal_id,
                "swarm_run_id": swarm.id,
            },
            [
                ["conversation", swarm.conversation_id],
                ["agent-swarm", swarm.id],
                ["agent-swarms", swarm.conversation_id],
            ],
        )


class SQLAlchemyAgentPlanState(AgentPlanStatePort):
    def __init__(
        self,
        *,
        projects: ProjectRepository,
        system_image: SystemImageRepository,
        source_binding_incomplete: Any,
        tools: Sequence[ToolDefinition],
    ) -> None:
        self._projects = projects
        self._system_image = system_image
        self._source_binding_incomplete = source_binding_incomplete
        self._known_tool_ids = frozenset(tool.tool_id for tool in tools)

    def project_exists(self, project_id: str) -> bool:
        return self._projects.get_project(project_id) is not None

    def source_binding_incomplete(self, project_id: str) -> bool:
        return self._source_binding_incomplete(project_id)

    def source_ingestion_statuses(self, project_id: str) -> tuple[str, ...]:
        snapshot = self._system_image.load_project_snapshot(project_id)
        return tuple(source.ingestion_status for source in snapshot.raw_assets)

    def has_materialized_context(self, project_id: str) -> bool:
        snapshot = self._system_image.load_project_snapshot(project_id)
        return bool(
            snapshot.knowledge_objects
            and snapshot.relationships
            and snapshot.metric_snapshots
        )

    def has_ready_official_baseline(self, project_id: str) -> bool:
        return any(
            baseline.kind == "official" and baseline.status == "ready"
            for baseline in self._system_image.load_project_snapshot(project_id).baselines
        )

    def known_tool_ids(self) -> frozenset[str]:
        return self._known_tool_ids


class SQLAlchemyAgentWorkflowState:
    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def workflow_id_for_goal(self, goal_id: str) -> str | None:
        goal = _required(
            self._repository.get_agent_goal(goal_id),
            "AgentGoal",
            goal_id,
        )
        return goal.workflow_id

    def accept_remote_goal(self, goal: AgentGoal) -> None:
        self._repository.upsert_goal(goal)


class SQLAlchemyAgentApplicationPorts:
    """Production Agent port composition backed by PostgreSQL facts."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        quality_loop: QualityLoopRepository,
        system_image: SystemImageRepository,
        tools: Sequence[ToolDefinition],
        runtime: AgentApplicationRuntimeAdapters,
    ) -> None:
        lifecycle_effects = AgentGoalLifecycleAdapters(
            project_goal=runtime.project_goal,
            record_goal_audit_event=runtime.record_goal_audit_event,
            append_text_message=runtime.append_text_message,
            push_goal_event=runtime.push_goal_event,
            push_conversation_event=runtime.push_conversation_event,
        )
        self.conversation_management = SQLAlchemyConversationManagementState(
            conversations,
            AgentConversationManagementRuntimeAdapters(
                resolve_scope=runtime.resolve_conversation_scope,
                current_user_id=runtime.current_user_id,
                require_project_access=runtime.require_project_access,
                require_conversation_access=runtime.require_conversation_access,
                can_access_conversation=runtime.can_access_conversation,
            ),
        )
        self.conversation_messages = SQLAlchemyConversationMessageState(
            conversations,
            AgentConversationCheckpointAdapters(
                maybe_create_summary_checkpoint=runtime.maybe_create_summary_checkpoint,
            ),
        )

        def record_source_binding_received(
            goal: AgentGoal,
            source_types: list[str],
        ) -> Any:
            return runtime.record_goal_audit_event(
                goal,
                action="agent.goal.source_binding_received",
                status=goal.status,
                summary=f"Source bindings received for AgentGoal: {goal.title}",
                actor=runtime.current_user_id(),
                actor_kind="user",
                metadata={"source_types": source_types},
            )

        self.conversation_runtime = DelegatingConversationMessageRuntimeAdapter(
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
        self.conversation_summaries = SQLAlchemyConversationSummaryState(conversations)
        self.events = DelegatingAgentConversationEventPublisher(
            AgentConversationEventAdapters(
                push_event=runtime.push_conversation_event,
            )
        )
        self.goal_lifecycle = SQLAlchemyAgentGoalLifecycleState(
            conversations,
            lifecycle_effects,
        )
        self.goal_projection = SQLAlchemyAgentGoalProjectionState(conversations)
        self.goal_explanations = DelegatingAgentGoalExplanationQueryAdapter(
            AgentGoalExplanationAdapters(
                get_goal=runtime.get_goal,
                get_checkpoint=runtime.get_checkpoint,
                get_tool_invocation=runtime.get_tool_invocation,
                list_tool_invocations=runtime.list_tool_invocations,
                list_agent_memory_items=runtime.list_agent_memory_items,
                list_audit_events=runtime.list_audit_events,
            )
        )
        self.loop_state = DelegatingAgentLoopStateAdapter(
            AgentLoopRuntimeAdapters(
                get_conversation=runtime.get_conversation,
                create_goal=runtime.create_goal_record,
                get_goal=runtime.get_goal,
            ),
            lifecycle_effects,
        )
        self.memory_state = SQLAlchemyAgentMemoryState(
            conversations=conversations,
            projects=projects,
            quality_loop=quality_loop,
            system_image=system_image,
            tools=tools,
            push_event=runtime.push_conversation_event,
        )
        self.swarm_state = SQLAlchemyAgentSwarmState(
            conversations,
            runtime.push_conversation_event,
        )
        self.planner_context = DelegatingAgentPlannerContextAdapter(
            AgentPlannerContextAdapters(
                memory_context=lambda conversation: runtime.build_memory_context(
                    conversation,
                    trace_retrieval=True,
                ),
                conversation_summary_fallback=runtime.conversation_summary_fallback,
                quality_state=runtime.quality_state,
            )
        )
        self.plan_state = SQLAlchemyAgentPlanState(
            projects=projects,
            system_image=system_image,
            source_binding_incomplete=runtime.source_binding_incomplete,
            tools=tools,
        )
        self.graph_state = DelegatingAgentGraphStateAdapter(
            AgentGraphLookupAdapters(
                get_goal=runtime.get_goal,
                get_conversation=runtime.get_conversation,
            ),
            AgentGraphToolRuntimeAdapters(
                create_tool_invocation=runtime.create_tool_invocation,
                confirm_tool_invocation=runtime.confirm_tool_invocation,
                get_tool_invocation=runtime.get_tool_invocation,
                available_tool_ids=lambda: (tool.tool_id for tool in tools),
            ),
            AgentGraphMemoryAdapters(
                create_summary_checkpoint=runtime.create_summary_checkpoint,
                record_memory_item=runtime.record_memory_item,
                build_memory_context=lambda conversation: runtime.build_memory_context(
                    conversation,
                    trace_retrieval=True,
                ),
            ),
            lifecycle_effects,
        )
        self.workflow_state = SQLAlchemyAgentWorkflowState(conversations)


__all__ = [
    "SQLAlchemyAgentApplicationPorts",
    "SQLAlchemyAgentGoalLifecycleState",
    "SQLAlchemyAgentMemoryState",
    "SQLAlchemyAgentPlanState",
    "SQLAlchemyConversationManagementState",
]
