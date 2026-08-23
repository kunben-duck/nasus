from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..agent.agent_models import AgentGoal, ConversationSession


@dataclass(frozen=True)
class DistributedStateSynchronizationDependencies:
    persist_goal: Callable[[AgentGoal], None]
    get_conversation: Callable[[str], ConversationSession | None]


class DistributedStateSynchronizationApplicationService:
    """Commit remote worker results into the durable Agent write model."""

    def __init__(
        self,
        dependencies: DistributedStateSynchronizationDependencies,
    ) -> None:
        self._dependencies = dependencies

    def accept_remote_goal(self, goal: AgentGoal) -> None:
        """Commit a worker result idempotently after validating its owner."""

        conversation = self._dependencies.get_conversation(goal.conversation_id)
        if conversation is None:
            raise RuntimeError(
                f"Temporal returned goal {goal.id} for unknown conversation "
                f"{goal.conversation_id}."
            )
        self._dependencies.persist_goal(goal)


__all__ = [
    "DistributedStateSynchronizationApplicationService",
    "DistributedStateSynchronizationDependencies",
]
