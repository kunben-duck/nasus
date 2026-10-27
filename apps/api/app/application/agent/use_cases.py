from __future__ import annotations

from typing import Any, Callable, Optional

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
from .turns import ConversationTurnApplicationService
from ..platform.events import PlatformEventApplicationService
from ..platform.errors import PlatformApplicationError
from ..platform.tool_models import ToolInvocation
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ...domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageArtifactUnavailable
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from ...domain.agent.resume_checkpoint import AgentResumeCheckpointChanged, InvalidAgentResumeCheckpoint
from ...domain.agent.image_plan_policy import is_pinned_image_plan
from ...domain.agent.runtime_models import ToolPlanStep
from .build_intent_entries import DIGEST_REF
from .resume_inputs import AgentGoalResumeRequest


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
        tool_broadcast_view: Callable[[ToolInvocation], ToolInvocation] | None = None,
    ) -> None:
        self._conversations = conversations
        self._events = events
        self._explanations = explanations
        self._goals = goals
        self._memory = memory
        self._messages = messages
        self._swarm = swarm
        self._turns: ConversationTurnApplicationService | None = None
        self._tool_broadcast_view = tool_broadcast_view

    def _conversation_view(self, conversation):
        if self._tool_broadcast_view is None:
            return conversation
        return conversation.model_copy(update={"tool_invocations": [
            self._tool_broadcast_view(item) for item in conversation.tool_invocations]})

    def bind_conversation_turns(
        self,
        turns: ConversationTurnApplicationService,
    ) -> None:
        self._turns = turns

    def ensure_conversation(self, payload: ConversationCreateRequest) -> Any:
        return self._conversation_view(self._conversations.ensure_conversation(payload))

    def list_conversations(
        self,
        *,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        space_type: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Any:
        return [self._conversation_view(item) for item in self._conversations.list_conversations(
            project_id=project_id,
            version_id=version_id,
            space_type=space_type,
            status=status,
            q=q,
        )]

    def search_conversations(self, q: str) -> Any:
        result = self._conversations.search_conversations(q)
        return {**result, "conversations": [self._conversation_view(item) for item in result["conversations"]]}

    def get_conversation(self, conversation_id: str) -> Any:
        return self._conversation_view(self._conversations.get_conversation(conversation_id))

    def list_conversation_messages(self, conversation_id: str, before_message_id: Optional[str] = None) -> Any:
        return self._conversations.list_conversation_messages(conversation_id, before_message_id)

    def archive_conversation(self, conversation_id: str, payload: ConversationArchiveRequest) -> Any:
        return self._conversation_view(self._conversations.archive_conversation(conversation_id, payload))

    def merge_conversation(self, conversation_id: str, payload: ConversationMergeRequest) -> Any:
        return self._conversations.merge_conversations(conversation_id, payload)

    async def post_message(self, conversation_id: str, payload: ConversationMessageRequest) -> Any:
        self._conversations.get_conversation(conversation_id)
        return await self._messages.post_message(
            conversation_id,
            payload.content,
            canonical_action_id=payload.canonical_action_id,
        )

    async def accept_message(
        self,
        conversation_id: str,
        payload: ConversationMessageRequest,
        *,
        idempotency_key: str,
        events_url: str,
        actor: Any = None,
        request_id: str | None = None,
    ) -> Any:
        self._conversations.get_conversation(conversation_id)
        if self._turns is None:
            raise RuntimeError("Conversation turn service is not configured")
        return await self._turns.accept_turn(
            conversation_id=conversation_id,
            content=payload.content,
            idempotency_key=idempotency_key,
            canonical_action_id=payload.canonical_action_id,
            events_url=events_url,
            actor=actor,
            request_id=request_id,
        )

    def get_conversation_turn(self, conversation_id: str, turn_id: str) -> Any:
        self._conversations.get_conversation(conversation_id)
        if self._turns is None:
            raise RuntimeError("Conversation turn service is not configured")
        turn = self._turns.get_turn(turn_id)
        if turn.conversation_id != conversation_id:
            raise KeyError(turn_id)
        return turn

    async def cancel_conversation_turn(self, conversation_id: str, turn_id: str) -> Any:
        self._conversations.get_conversation(conversation_id)
        if self._turns is None:
            raise RuntimeError("Conversation turn service is not configured")
        return await self._turns.cancel_turn(conversation_id, turn_id)

    async def stream_conversation_events(self, conversation_id: str, last_event_id: str | None = None):
        async for event in self._events.stream_conversation_events(conversation_id, last_event_id):
            yield event

    async def create_manual_goal(self, payload: AgentGoalCreateRequest) -> Any:
        conversation = self._conversations.get_conversation(payload.conversation_id)
        if any(ref.startswith(DIGEST_REF) for ref in payload.target_refs):
            projects = [ref.removeprefix("project:") for ref in payload.target_refs if ref.startswith("project:")]
            if (conversation.space_type not in {"project", "knowledge"} or not conversation.project_id
                    or projects != [conversation.project_id] or payload.project_id not in {None, conversation.project_id}):
                raise AgentPlanPolicyViolation("saved_build_intent_conversation_changed", "A saved entry must belong to its project conversation.")
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
        try:
            return await self._memory.get_context_view(
                conversation_id=conversation_id,
                agent_goal_id=agent_goal_id,
                space_ref=space_ref,
            )
        except StaleSourceAccessScope as exc:
            raise PlatformApplicationError(
                "source_scope_changed", "Source access changed. Rebuild the context.", 409,
            ) from exc
        except SourceAccessDenied as exc:
            raise PlatformApplicationError("source_access_denied", "Source is not available.", 403) from exc
        except PublicationChanged as exc:
            raise PlatformApplicationError("publication_changed", "Published image changed. Rebuild the context.", 409) from exc
        except (PublicationIntegrityError, ImageRevisionIntegrityError) as exc:
            raise PlatformApplicationError("image_integrity_failed", "Published image failed integrity verification.", 502) from exc
        except ImageArtifactUnavailable as exc:
            raise PlatformApplicationError("image_artifact_unavailable", "Published image is unavailable.", 503) from exc

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

    async def resume_goal(self, goal_id: str, request: AgentGoalResumeRequest | None = None) -> Any:
        goal = self.get_agent_goal(goal_id)
        try:
            if request is not None:
                expected_resume = request.checkpoint()
                expected_resume.require_scope(goal.model_dump(mode="json"))
                return await self._goals.resume_goal(goal_id, expected_resume=expected_resume)
            if is_pinned_image_plan([ToolPlanStep(step.selected_tool_id, step.tool_input_payload)
                    for step in goal.steps if step.selected_tool_id], goal.target_refs):
                raise PlatformApplicationError("agent_checkpoint_required", "Reload and submit the displayed goal checkpoint before continuing.", 428)
            return await self._goals.resume_goal(goal_id)
        except AgentResumeCheckpointChanged as exc:
            raise PlatformApplicationError("agent_checkpoint_changed", "The goal checkpoint changed. Reload before continuing.", 409) from exc
        except InvalidAgentResumeCheckpoint as exc:
            raise PlatformApplicationError("agent_checkpoint_invalid", "The goal checkpoint cannot be safely resumed.", 409) from exc
        except AgentPlanPolicyViolation as exc:
            raise PlatformApplicationError(exc.code, "The fixed goal checkpoint changed. Reload before continuing.", 409) from exc
        except StaleSourceAccessScope as exc:
            raise PlatformApplicationError("source_scope_changed", "Source access changed. Reload before continuing.", 409) from exc
        except SourceAccessDenied as exc:
            raise PlatformApplicationError("source_access_denied", "Source is not available.", 403) from exc
        except BuildPlanIntegrityError as exc:
            raise PlatformApplicationError("build_integrity_failed", "The fixed build artifact failed verification.", 409) from exc
        except ImageRevisionIntegrityError as exc:
            raise PlatformApplicationError("image_integrity_failed", "The fixed image failed verification.", 502) from exc
        except ImageArtifactUnavailable as exc:
            raise PlatformApplicationError("image_artifact_unavailable", "The fixed image is unavailable.", 503) from exc

    async def add_goal_feedback(self, goal_id: str, payload: AgentGoalFeedbackRequest) -> Any:
        self.get_agent_goal(goal_id)
        return await self._goals.add_feedback(goal_id, payload.feedback)
