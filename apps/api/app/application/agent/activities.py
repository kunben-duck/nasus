from __future__ import annotations

from typing import Protocol

from .agent_models import AgentGoal
from ...domain.agent.runtime_models import AgentGoalProposal


class AgentLoopActivityRuntime(Protocol):
    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        ...

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        ...


class AgentGoalProjector(Protocol):
    def upsert_in_conversation(self, goal: AgentGoal) -> None:
        ...


class AgentWorkflowActivityApplicationService:
    """Application boundary executed by Temporal activities.

    Temporal owns durable scheduling; this service owns the application-level
    transition into the Agent loop and projection update. It has no SDK, HTTP,
    database, or compatibility-store dependency.
    """

    def __init__(
        self,
        *,
        loop_runtime: AgentLoopActivityRuntime,
        goal_projector: AgentGoalProjector,
    ) -> None:
        self._loop_runtime = loop_runtime
        self._goal_projector = goal_projector

    async def start_goal(
        self,
        *,
        conversation_id: str,
        proposal: AgentGoalProposal,
        workflow_id: str | None,
    ) -> AgentGoal:
        goal = await self._loop_runtime.start_goal(conversation_id, proposal)
        if workflow_id and goal.workflow_id != workflow_id:
            goal.workflow_id = workflow_id
            self._goal_projector.upsert_in_conversation(goal)
        return goal

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        return await self._loop_runtime.resume_goal(goal_id)


__all__ = ["AgentWorkflowActivityApplicationService"]
