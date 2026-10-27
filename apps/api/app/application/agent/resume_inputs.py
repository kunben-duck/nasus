"""The displayed aggregate is a precondition, never an authorization grant."""
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict

from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint


class AgentGoalResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_goal: Dict[str, Any]

    def checkpoint(self) -> AgentResumeCheckpoint:
        return AgentResumeCheckpoint.capture(self.expected_goal)
