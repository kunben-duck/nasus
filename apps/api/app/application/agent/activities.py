from __future__ import annotations

from typing import Protocol

from .agent_models import AgentGoal
from ...domain.agent.runtime_models import AgentGoalProposal
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.agent.plan_policy import AgentPlanPolicyViolation


class AgentLoopActivityRuntime(Protocol):
    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal, *, workflow_id: str | None = None) -> AgentGoal:
        ...

    async def resume_goal(self, goal_id: str, *, expected_resume: AgentResumeCheckpoint | None = None) -> AgentGoal:
        ...

    def get_goal(self, goal_id: str) -> AgentGoal:
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
        if workflow_id is None:
            return await self._loop_runtime.start_goal(conversation_id, proposal)
        goal = await self._loop_runtime.start_goal(conversation_id, proposal, workflow_id=workflow_id)
        if goal.workflow_id != workflow_id:
            raise AgentPlanPolicyViolation("agent_start_scope_changed", "The activity cannot replace the original goal controller.")
        return goal

    async def resume_goal(self, goal_id: str, *, expected_resume: AgentResumeCheckpoint | None = None) -> AgentGoal:
        if expected_resume is None:
            return await self._loop_runtime.resume_goal(goal_id)
        return await self._loop_runtime.resume_goal(goal_id, expected_resume=expected_resume)

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._loop_runtime.get_goal(goal_id)


__all__ = ["AgentWorkflowActivityApplicationService"]
