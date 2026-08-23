from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from .agent_models import AgentGoal, ConversationSession
from ...domain.agent.runtime_models import ModelUsage, ToolPlanStep


AgentReplanAction = Literal["keep", "replace_remaining", "complete"]


@dataclass(frozen=True)
class AgentReplanRequest:
    conversation: ConversationSession
    goal: AgentGoal
    observation_summary: str
    completed_steps: list[ToolPlanStep] = field(default_factory=list)
    remaining_steps: list[ToolPlanStep] = field(default_factory=list)


@dataclass(frozen=True)
class AgentReplanDecision:
    action: AgentReplanAction
    rationale: str
    planned_tools: list[ToolPlanStep] = field(default_factory=list)
    confidence: float = 0.0
    planner_kind: str = "initial_plan"
    model_usage: ModelUsage = field(default_factory=ModelUsage)

    @classmethod
    def keep(
        cls,
        rationale: str,
        *,
        confidence: float = 0.0,
        planner_kind: str = "initial_plan",
        model_usage: ModelUsage | None = None,
    ) -> "AgentReplanDecision":
        return cls(
            action="keep",
            rationale=rationale,
            confidence=confidence,
            planner_kind=planner_kind,
            model_usage=model_usage or ModelUsage(),
        )


class AgentReplanner(Protocol):
    async def replan(self, request: AgentReplanRequest) -> AgentReplanDecision:
        ...


__all__ = [
    "AgentReplanAction",
    "AgentReplanDecision",
    "AgentReplanRequest",
    "AgentReplanner",
]
