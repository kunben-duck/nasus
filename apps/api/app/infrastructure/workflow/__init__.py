"""Workflow runtime gateways."""

from .agent_graph_factory import build_agent_graph_runtime, selected_agent_graph_runtime_kind
from .agent_workflow_factory import build_agent_workflow_runtime, selected_agent_workflow_runtime_kind
from .langgraph_agent_gateway import LangGraphAgentLoopGateway
from .readiness import LangGraphCheckpointReadinessProbe, TemporalWorkflowReadinessProbe
from .temporal_agent_gateway import TemporalClientWorkflowGateway


_WORKER_EXPORTS = {
    "AgentGoalWorkflowActivityService",
    "build_nasus_agent_goal_workflow",
    "build_temporal_activity_definitions",
    "run_temporal_agent_goal_worker",
}


def __getattr__(name: str):
    if name in _WORKER_EXPORTS:
        from . import agent_goal_workflow_worker

        return getattr(agent_goal_workflow_worker, name)
    raise AttributeError(name)


__all__ = [
    "AgentGoalWorkflowActivityService",
    "build_nasus_agent_goal_workflow",
    "build_agent_graph_runtime",
    "build_agent_workflow_runtime",
    "build_temporal_activity_definitions",
    "LangGraphAgentLoopGateway",
    "LangGraphCheckpointReadinessProbe",
    "run_temporal_agent_goal_worker",
    "selected_agent_graph_runtime_kind",
    "selected_agent_workflow_runtime_kind",
    "TemporalClientWorkflowGateway",
    "TemporalWorkflowReadinessProbe",
]
