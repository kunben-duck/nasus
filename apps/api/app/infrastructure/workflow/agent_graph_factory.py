from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ...application.agent.graph import (
    AgentGraphRuntime,
    AgentGraphRuntimeKind,
    LangGraphAgentGraphRuntime,
    LangGraphGateway,
    LocalAgentGraphRuntime,
)
from ...application.agent.plans import AgentGoalPlanCompiler
from ...application.agent.ports import AgentGraphStatePort
from ...domain.agent.state_machine import AgentGoalStateMachine
from .langgraph_agent_gateway import LangGraphAgentLoopGateway

if TYPE_CHECKING:
    from ...application.agent.replanning import AgentReplanner


def selected_agent_graph_runtime_kind() -> AgentGraphRuntimeKind:
    raw_value = os.getenv("NASUS_AGENT_GRAPH_RUNTIME", "local").strip().lower()
    if raw_value in {"", "local"}:
        return "local"
    if raw_value == "langgraph":
        return "langgraph"
    raise RuntimeError(
        "NASUS_AGENT_GRAPH_RUNTIME must be either 'local' or 'langgraph'. "
        f"Received: {raw_value!r}."
    )


def build_agent_graph_runtime(
    state: AgentGraphStatePort,
    state_machine: AgentGoalStateMachine,
    plan_compiler: AgentGoalPlanCompiler,
    *,
    graph_kind: AgentGraphRuntimeKind | None = None,
    langgraph_gateway: LangGraphGateway | None = None,
    replanner: "AgentReplanner | None" = None,
) -> AgentGraphRuntime:
    selected_kind = graph_kind or selected_agent_graph_runtime_kind()
    if selected_kind == "local":
        return LocalAgentGraphRuntime(
            state,
            state_machine,
            plan_compiler,
            replanner=replanner,
        )
    if langgraph_gateway is None:
        langgraph_gateway = LangGraphAgentLoopGateway(
            state,
            state_machine,
            plan_compiler,
            replanner=replanner,
        )
    return LangGraphAgentGraphRuntime(langgraph_gateway)


__all__ = [
    "build_agent_graph_runtime",
    "selected_agent_graph_runtime_kind",
]
