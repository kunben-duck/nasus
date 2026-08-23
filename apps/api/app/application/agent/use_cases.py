from __future__ import annotations

from typing import Any, Optional

from .agent_models import (
    AgentGoalCreateRequest,
    AgentGoalBudgetUpdateRequest,
    AgentGoalFeedbackRequest,
    AgentMemoryCheckpointRequest,
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationMergeRequest,
    ConversationMessageRequest,
)
from .explanations import AgentGoalExplanationApplicationService
from .memory import AgentMemoryManager
from ..platform.events import PlatformEventApplicationService


class AgentApplicationService:
    """Agent and conversation use cases.

    This service is the HTTP-facing application boundary for the migration.
    It composes explicit agent use-case services. Compatibility projection
    adapters remain an infrastructure concern of the composition root.
    """

    def __init__(
        self,
        *,
        conversations: Any,
        events: PlatformEventApplicationService,
        explanations: AgentGoalExplanationApplicationService,
        goals: Any,
        memory: AgentMemoryManager,
        messages: Any,
        swarm: Any,
    ) -> None:
        self._conversations = conversations
        self._events = events
        self._explanations = explanations
        self._goals = goals
        self._memory = memory
        self._messages = messages
        self._swarm = swarm

    def ensure_conversation(self, payload: ConversationCreateRequest) -> Any:
        return self._conversations.ensure_conversation(payload)

    def list_conversations(
        self,
        *,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        space_type: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Any:
        return self._conversations.list_conversations(
            project_id=project_id,
            version_id=version_id,
            space_type=space_type,
            status=status,
            q=q,
        )

    def search_conversations(self, q: str) -> Any:
        return self._conversations.search_conversations(q)

    def get_conversation(self, conversation_id: str) -> Any:
        return self._conversations.get_conversation(conversation_id)

    def list_conversation_messages(self, conversation_id: str, before_message_id: Optional[str] = None) -> Any:
        return self._conversations.list_conversation_messages(conversation_id, before_message_id)

    def archive_conversation(self, conversation_id: str, payload: ConversationArchiveRequest) -> Any:
        return self._conversations.archive_conversation(conversation_id, payload)

    def merge_conversation(self, conversation_id: str, payload: ConversationMergeRequest) -> Any:
        return self._conversations.merge_conversations(conversation_id, payload)

    async def post_message(self, conversation_id: str, payload: ConversationMessageRequest) -> Any:
        self._conversations.get_conversation(conversation_id)
        return await self._messages.post_message(
            conversation_id,
            payload.content,
            canonical_action_id=payload.canonical_action_id,
        )

    async def stream_conversation_events(self, conversation_id: str, last_event_id: str | None = None):
        async for event in self._events.stream_conversation_events(conversation_id, last_event_id):
            yield event

    async def create_manual_goal(self, payload: AgentGoalCreateRequest) -> Any:
        conversation = self._conversations.get_conversation(payload.conversation_id)
        if payload.project_id and payload.project_id != conversation.project_id:
            raise ValueError("AgentGoal project_id must match the conversation project scope.")
        return await self._goals.create_manual_goal(payload)

    def get_agent_goal(self, goal_id: str) -> Any:
        goal = self._goals.get_goal(goal_id)
        self._conversations.get_conversation(goal.conversation_id)
        return goal

    def get_agent_goal_checkpoint(self, goal_id: str) -> Any:
        self.get_agent_goal(goal_id)
        return self._goals.get_checkpoint(goal_id)

    def get_agent_goal_explanation(self, goal_id: str) -> Any:
        self.get_agent_goal(goal_id)
        return self._explanations.get_explanation(goal_id)

    def update_agent_goal_budget(
        self,
        goal_id: str,
        payload: AgentGoalBudgetUpdateRequest,
    ) -> Any:
        self.get_agent_goal(goal_id)
        return self._goals.update_budget(goal_id, payload)

    async def get_agent_memory_context(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        space_ref: Optional[str] = None,
    ) -> Any:
        if conversation_id:
            self._conversations.get_conversation(conversation_id)
        if agent_goal_id:
            self.get_agent_goal(agent_goal_id)
        return await self._memory.get_context_view(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )

    async def create_agent_memory_checkpoint(self, payload: AgentMemoryCheckpointRequest) -> Any:
        if payload.conversation_id:
            self._conversations.get_conversation(payload.conversation_id)
        if payload.agent_goal_id:
            self.get_agent_goal(payload.agent_goal_id)
        return await self._memory.create_summary_checkpoint(
            conversation_id=payload.conversation_id,
            agent_goal_id=payload.agent_goal_id,
            space_ref=payload.space_ref,
            created_by=payload.created_by,
        )

    async def stream_goal_events(self, goal_id: str, last_event_id: str | None = None):
        async for event in self._events.stream_goal_events(goal_id, last_event_id):
            yield event

    def get_agent_swarm(self, swarm_id: str) -> Any:
        swarm = self._swarm.get_swarm(swarm_id)
        self._conversations.get_conversation(swarm.conversation_id)
        return swarm

    def list_agent_swarms(
        self,
        *,
        conversation_id: str | None = None,
        parent_goal_id: str | None = None,
    ) -> Any:
        if conversation_id:
            self._conversations.get_conversation(conversation_id)
        if parent_goal_id:
            goal = self.get_agent_goal(parent_goal_id)
            if conversation_id and goal.conversation_id != conversation_id:
                raise ValueError("parent_goal_id does not belong to conversation_id")
        swarms = self._swarm.list_swarms(
            conversation_id=conversation_id,
            parent_goal_id=parent_goal_id,
        )
        for swarm in swarms:
            self._conversations.get_conversation(swarm.conversation_id)
        return list(swarms)

    async def run_system_image_materialization_swarm(
        self,
        *,
        agent_goal_id: str | None,
        conversation_id: str | None,
        project_id: str,
        invocation_id: str,
        sources: Any,
    ) -> Any | None:
        if not agent_goal_id or not conversation_id or not self._goals.has_goal(agent_goal_id):
            return None
        return await self._swarm.run_system_image_materialization_swarm(
            parent_goal_id=agent_goal_id,
            conversation_id=conversation_id,
            project_id=project_id,
            invocation_id=invocation_id,
            sources=sources,
        )

    async def stream_swarm_events(self, swarm_id: str, last_event_id: str | None = None):
        async for event in self._events.stream_swarm_events(swarm_id, last_event_id):
            yield event

    async def interrupt_goal(self, goal_id: str) -> Any:
        self.get_agent_goal(goal_id)
        return await self._goals.interrupt_goal(goal_id)

    async def resume_goal(self, goal_id: str) -> Any:
        self.get_agent_goal(goal_id)
        return await self._goals.resume_goal(goal_id)

    async def add_goal_feedback(self, goal_id: str, payload: AgentGoalFeedbackRequest) -> Any:
        self.get_agent_goal(goal_id)
        return await self._goals.add_feedback(goal_id, payload.feedback)
