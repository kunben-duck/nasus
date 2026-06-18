from __future__ import annotations

from dataclasses import dataclass
import os


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


@dataclass(frozen=True)
class TemporalGatewayConfig:
    address: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "nasus-agent-goals"
    workflow_type: str = "NasusAgentGoalWorkflow"
    current_goal_query: str = "current_goal"
    resume_signal: str = "resume_goal"
    workflow_id_prefix: str = "nasus-agent-goal"


@dataclass(frozen=True)
class LangGraphGatewayConfig:
    graph_name: str = "nasus-agent-loop"


def temporal_gateway_config_from_env() -> TemporalGatewayConfig:
    return TemporalGatewayConfig(
        address=_env_str("NASUS_TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=_env_str("NASUS_TEMPORAL_NAMESPACE", "default"),
        task_queue=_env_str("NASUS_TEMPORAL_TASK_QUEUE", "nasus-agent-goals"),
        workflow_type=_env_str("NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW", "NasusAgentGoalWorkflow"),
        current_goal_query=_env_str("NASUS_TEMPORAL_CURRENT_GOAL_QUERY", "current_goal"),
        resume_signal=_env_str("NASUS_TEMPORAL_RESUME_SIGNAL", "resume_goal"),
        workflow_id_prefix=_env_str("NASUS_TEMPORAL_WORKFLOW_ID_PREFIX", "nasus-agent-goal"),
    )


def langgraph_gateway_config_from_env() -> LangGraphGatewayConfig:
    return LangGraphGatewayConfig(
        graph_name=_env_str("NASUS_LANGGRAPH_AGENT_LOOP_GRAPH", "nasus-agent-loop"),
    )
