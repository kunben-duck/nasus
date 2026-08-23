from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

from sqlalchemy import Engine, text

from ..config.agent_runtime_config import (
    LangGraphGatewayConfig,
    TemporalGatewayConfig,
    langgraph_gateway_config_from_env,
    temporal_gateway_config_from_env,
)


class TemporalWorkflowReadinessProbe:
    """Check the selected workflow runtime and Temporal frontend reachability."""

    name = "agent_workflow"

    def __init__(
        self,
        config: TemporalGatewayConfig | None = None,
        *,
        runtime_kind: str | None = None,
        timeout_seconds: float = 1.5,
    ) -> None:
        self._config = config or temporal_gateway_config_from_env()
        self._runtime_kind = (
            runtime_kind
            or os.getenv("NASUS_AGENT_WORKFLOW_RUNTIME", "local")
        ).strip().lower()
        self._timeout_seconds = timeout_seconds

    def check(self) -> dict[str, str]:
        if self._runtime_kind == "local":
            return {
                "backend": "local",
                "status": "development_only",
            }
        if self._runtime_kind != "temporal":
            raise RuntimeError(
                f"unsupported agent workflow runtime: {self._runtime_kind or 'empty'}"
            )

        host, port = self._host_and_port(self._config.address)
        with socket.create_connection((host, port), timeout=self._timeout_seconds):
            pass
        return {
            "backend": "temporal",
            "address": self._config.address,
            "namespace": self._config.namespace,
            "task_queue": self._config.task_queue,
        }

    @staticmethod
    def _host_and_port(address: str) -> tuple[str, int]:
        candidate = address.strip()
        parsed = urlsplit(candidate if "://" in candidate else f"tcp://{candidate}")
        if not parsed.hostname or not parsed.port:
            raise RuntimeError(f"invalid Temporal address: {address!r}")
        return parsed.hostname, parsed.port


class LangGraphCheckpointReadinessProbe:
    """Verify the selected graph runtime and durable checkpoint schema."""

    name = "agent_checkpoint"

    def __init__(
        self,
        engine: Engine,
        config: LangGraphGatewayConfig | None = None,
        *,
        runtime_kind: str | None = None,
    ) -> None:
        self._engine = engine
        self._config = config or langgraph_gateway_config_from_env()
        self._runtime_kind = (
            runtime_kind
            or os.getenv("NASUS_AGENT_GRAPH_RUNTIME", "local")
        ).strip().lower()

    def check(self) -> dict[str, str]:
        if self._runtime_kind == "local":
            return {
                "backend": "memory",
                "status": "development_only",
            }
        if self._runtime_kind != "langgraph":
            raise RuntimeError(
                f"unsupported agent graph runtime: {self._runtime_kind or 'empty'}"
            )
        if self._config.checkpoint_backend != "postgres":
            return {
                "backend": self._config.checkpoint_backend,
                "status": "development_only",
            }

        with self._engine.connect() as connection:
            migration_count = connection.execute(
                text("SELECT count(*) FROM checkpoint_migrations")
            ).scalar_one()
            connection.execute(text("SELECT 1 FROM checkpoints LIMIT 1"))
        if int(migration_count) <= 0:
            raise RuntimeError("LangGraph checkpoint migrations are not initialized")
        return {
            "backend": "postgres",
            "graph_name": self._config.graph_name,
            "migration_count": str(migration_count),
        }


__all__ = [
    "LangGraphCheckpointReadinessProbe",
    "TemporalWorkflowReadinessProbe",
]
