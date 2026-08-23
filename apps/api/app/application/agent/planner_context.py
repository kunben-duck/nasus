from __future__ import annotations

from .agent_models import ConversationSession
from .ports import AgentPlannerContextPort
from ...domain.agent.memory import AgentMemoryContext


class AgentPlannerContextApplicationService:
    """Builds deterministic planner context from current project and quality state."""

    def __init__(self, context: AgentPlannerContextPort) -> None:
        self._context = context

    async def memory_context(self, conversation: ConversationSession) -> AgentMemoryContext:
        return await self._context.memory_context(conversation)

    def conversation_summary_fallback(self, conversation: ConversationSession) -> str:
        return self._context.conversation_summary_fallback(conversation)

    def quality_state(self, project_id: str | None, us_id: str | None) -> dict[str, str]:
        return self._context.quality_state(project_id, us_id)
