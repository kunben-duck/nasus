"""Conditional persistence for a prepared resume; admission/dispatch is separate."""
from typing import Protocol

from .agent_models import AgentGoal
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint


class AgentResumeCommitPort(Protocol):
    def is_consumed(self, checkpoint: AgentResumeCheckpoint) -> bool:
        ...

    def commit_at_checkpoint(self, goal: AgentGoal, checkpoint: AgentResumeCheckpoint) -> None:
        """Compare persisted state and save the whole goal in the same transaction."""
        ...
