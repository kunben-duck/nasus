from __future__ import annotations

from .agent_models import AgentGoal
from .ports import AgentGoalProjectionStatePort


class AgentGoalProjectionApplicationService:
    """Keeps ConversationSession.agent_goals aligned with AgentGoal facts."""

    def __init__(self, state: AgentGoalProjectionStatePort) -> None:
        self._state = state

    def upsert_in_conversation(self, goal: AgentGoal) -> None:
        conversation = self._state.get_conversation(goal.conversation_id)
        existing_index = next(
            (index for index, current in enumerate(conversation.agent_goals) if current.id == goal.id),
            None,
        )
        if existing_index is None:
            conversation.agent_goals.append(goal)
        else:
            conversation.agent_goals[existing_index] = goal
        self._state.persist_goal_projection(conversation, goal)


__all__ = ["AgentGoalProjectionApplicationService"]
