from __future__ import annotations

from dataclasses import dataclass
import os


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive number.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive number.")
    return value


def _env_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


@dataclass(frozen=True)
class TemporalGatewayConfig:
    address: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "nasus-agent-goals"
    workflow_type: str = "NasusAgentGoalWorkflow"
    current_goal_query: str = "current_goal"
    resume_signal: str = "resume_goal"
    workflow_id_prefix: str = "nasus-agent-goal"
    query_timeout_seconds: float = 30.0
    query_poll_interval_seconds: float = 0.1
    max_concurrent_activities: int = 1


@dataclass(frozen=True)
class LangGraphGatewayConfig:
    graph_name: str = "nasus-agent-loop"
    checkpoint_backend: str = "memory"
    database_url: str = ""

    @property
    def psycopg_connection_string(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "NASUS_DATABASE_URL is required when NASUS_LANGGRAPH_CHECKPOINT_BACKEND=postgres."
            )
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def temporal_gateway_config_from_env() -> TemporalGatewayConfig:
    return TemporalGatewayConfig(
        address=_env_str("NASUS_TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=_env_str("NASUS_TEMPORAL_NAMESPACE", "default"),
        task_queue=_env_str("NASUS_TEMPORAL_TASK_QUEUE", "nasus-agent-goals"),
        workflow_type=_env_str("NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW", "NasusAgentGoalWorkflow"),
        current_goal_query=_env_str("NASUS_TEMPORAL_CURRENT_GOAL_QUERY", "current_goal"),
        resume_signal=_env_str("NASUS_TEMPORAL_RESUME_SIGNAL", "resume_goal"),
        workflow_id_prefix=_env_str("NASUS_TEMPORAL_WORKFLOW_ID_PREFIX", "nasus-agent-goal"),
        query_timeout_seconds=_env_positive_float(
            "NASUS_TEMPORAL_QUERY_TIMEOUT_SECONDS",
            30.0,
        ),
        query_poll_interval_seconds=_env_positive_float(
            "NASUS_TEMPORAL_QUERY_POLL_INTERVAL_SECONDS",
            0.1,
        ),
        max_concurrent_activities=_env_positive_int(
            "NASUS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES",
            1,
        ),
    )


def langgraph_gateway_config_from_env() -> LangGraphGatewayConfig:
    checkpoint_backend = _env_str("NASUS_LANGGRAPH_CHECKPOINT_BACKEND", "memory").lower()
    if checkpoint_backend not in {"memory", "postgres"}:
        raise RuntimeError(
            "NASUS_LANGGRAPH_CHECKPOINT_BACKEND must be either 'memory' or 'postgres'."
        )
    return LangGraphGatewayConfig(
        graph_name=_env_str("NASUS_LANGGRAPH_AGENT_LOOP_GRAPH", "nasus-agent-loop"),
        checkpoint_backend=checkpoint_backend,
        database_url=os.getenv("NASUS_DATABASE_URL", "").strip(),
    )
