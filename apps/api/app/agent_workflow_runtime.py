from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal, Protocol

from .agent_goal_state_machine import AgentGoalRuntimeCheckpoint
from .agent_runtime_models import AgentGoalProposal
from .models import AgentGoal


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


def selected_agent_workflow_runtime_kind() -> AgentWorkflowRuntimeKind:
    raw_value = os.getenv("NASUS_AGENT_WORKFLOW_RUNTIME", "local").strip().lower()
    if raw_value in {"", "local"}:
        return "local"
    if raw_value == "temporal":
        return "temporal"
    raise RuntimeError(
        "NASUS_AGENT_WORKFLOW_RUNTIME must be either 'local' or 'temporal'. "
        f"Received: {raw_value!r}."
    )


def build_agent_workflow_runtime(
    loop_runtime: AgentWorkflowRuntime,
    *,
    runtime_kind: AgentWorkflowRuntimeKind | None = None,
    temporal_gateway: TemporalWorkflowGateway | None = None,
) -> AgentWorkflowRuntime:
    selected_kind = runtime_kind or selected_agent_workflow_runtime_kind()
    if selected_kind == "local":
        return LocalAgentWorkflowRuntime(loop_runtime)
    if temporal_gateway is None:
        from .temporal_agent_gateway import TemporalClientWorkflowGateway

        store = getattr(loop_runtime, "store", None)
        goal_state_sink = None
        if store is not None and hasattr(store, "conversation_repository") and hasattr(store, "_upsert_goal_in_conversation"):
            def goal_state_sink(goal: AgentGoal) -> None:
                store.agent_goals[goal.id] = goal
                store.conversation_repository.upsert_goal(goal)
                store._upsert_goal_in_conversation(goal)

        temporal_gateway = TemporalClientWorkflowGateway(
            checkpoint_provider=loop_runtime.checkpoint,
            workflow_id_provider=(
                (lambda goal_id: store.get_agent_goal(goal_id).workflow_id)
                if store is not None and hasattr(store, "get_agent_goal")
                else None
            ),
            goal_state_sink=goal_state_sink,
        )
    return TemporalAgentWorkflowRuntime(temporal_gateway)
