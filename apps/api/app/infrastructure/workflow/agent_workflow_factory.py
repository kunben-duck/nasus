from __future__ import annotations

import os

from ...application.agent.ports import AgentWorkflowStatePort
from ...application.agent.workflow import (
    AgentWorkflowRuntime,
    AgentWorkflowRuntimeKind,
    LocalAgentWorkflowRuntime,
    TemporalAgentWorkflowRuntime,
    TemporalWorkflowGateway,
)
from .temporal_agent_gateway import TemporalClientWorkflowGateway


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
    workflow_state: AgentWorkflowStatePort | None = None,
) -> AgentWorkflowRuntime:
    selected_kind = runtime_kind or selected_agent_workflow_runtime_kind()
    if selected_kind == "local":
        return LocalAgentWorkflowRuntime(loop_runtime)
    if temporal_gateway is None:
        temporal_gateway = TemporalClientWorkflowGateway(
            checkpoint_provider=loop_runtime.checkpoint,
            workflow_id_provider=(
                workflow_state.workflow_id_for_goal
                if workflow_state is not None
                else None
            ),
            goal_state_sink=(
                workflow_state.accept_remote_goal
                if workflow_state is not None
                else None
            ),
        )
    return TemporalAgentWorkflowRuntime(temporal_gateway)


__all__ = [
    "build_agent_workflow_runtime",
    "selected_agent_workflow_runtime_kind",
]
