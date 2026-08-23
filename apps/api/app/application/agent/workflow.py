from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .agent_models import AgentGoal
from ...domain.agent.runtime_models import AgentGoalProposal
from ...domain.agent.state_machine import AgentGoalRuntimeCheckpoint


class AgentWorkflowRuntime(Protocol):
    runtime_kind: str

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        ...

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        ...

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        ...


class TemporalWorkflowGateway(Protocol):
    """Boundary for a Temporal SDK-backed AgentGoal workflow implementation."""

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        ...

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        ...

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        ...


@dataclass
class LocalAgentWorkflowRuntime:
    """Local workflow-runtime adapter used until Temporal is wired as the lifecycle backend."""

    loop_runtime: AgentWorkflowRuntime
    runtime_kind: str = "local"

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        return await self.loop_runtime.start_goal(conversation_id, proposal)

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        return await self.loop_runtime.resume_goal(goal_id)

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        return self.loop_runtime.checkpoint(goal_id)


@dataclass
class TemporalAgentWorkflowRuntime:
    """Workflow adapter for Temporal-backed AgentGoal execution.

    The actual Temporal SDK client is intentionally isolated behind
    TemporalWorkflowGateway so application code never imports Temporal directly.
    """

    gateway: TemporalWorkflowGateway
    runtime_kind: str = "temporal"

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        return await self.gateway.start_goal(conversation_id, proposal)

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        return await self.gateway.resume_goal(goal_id)

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        return self.gateway.checkpoint(goal_id)


AgentWorkflowRuntimeKind = Literal["local", "temporal"]


__all__ = [
    "AgentWorkflowRuntime",
    "AgentWorkflowRuntimeKind",
    "LocalAgentWorkflowRuntime",
    "TemporalAgentWorkflowRuntime",
    "TemporalWorkflowGateway",
]
