from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from time import monotonic
from typing import Any, Awaitable, Callable, Optional, Protocol
from uuid import uuid4

from ...application.agent.agent_models import AgentGoal
from ...application.platform.actor_context import current_actor
from ...domain.agent.state_machine import AgentGoalRuntimeCheckpoint
from ..config.agent_runtime_config import TemporalGatewayConfig, temporal_gateway_config_from_env
from ...domain.agent.runtime_models import AgentGoalProposal


class TemporalWorkflowHandleLike(Protocol):
    async def query(self, query: str, *args: Any) -> Any:
        ...

    async def signal(self, signal: str, *args: Any) -> None:
        ...


class TemporalClientLike(Protocol):
    async def start_workflow(self, workflow: str, *args: Any, id: str, task_queue: str) -> TemporalWorkflowHandleLike:
        ...

    def get_workflow_handle(self, workflow_id: str) -> TemporalWorkflowHandleLike:
        ...


TemporalClientFactory = Callable[[TemporalGatewayConfig], Awaitable[TemporalClientLike]]
CheckpointProvider = Callable[[str], AgentGoalRuntimeCheckpoint]
WorkflowIdProvider = Callable[[str], Optional[str]]
GoalStateSink = Callable[[AgentGoal], None]


class TemporalClientWorkflowGateway:
    """Temporal-backed AgentGoal gateway.

    The API service owns orchestration boundaries, but the durable lifecycle is
    delegated to a separately hosted Temporal worker. The worker contract is:
    start `workflow_type` with the serialized proposal payload, expose a
    `current_goal` query, and accept a `resume_goal` signal.
    """

    def __init__(
        self,
        config: TemporalGatewayConfig | None = None,
        *,
        client_factory: TemporalClientFactory | None = None,
        checkpoint_provider: CheckpointProvider | None = None,
        workflow_id_provider: WorkflowIdProvider | None = None,
        goal_state_sink: GoalStateSink | None = None,
    ) -> None:
        self.config = config or temporal_gateway_config_from_env()
        self._client_factory = client_factory or self._default_client_factory
        self._checkpoint_provider = checkpoint_provider
        self._workflow_id_provider = workflow_id_provider
        self._goal_state_sink = goal_state_sink
        self._client: TemporalClientLike | None = None

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        client = await self._client_instance()
        workflow_id = f"{self.config.workflow_id_prefix}-{uuid4().hex[:12]}"
        handle = await client.start_workflow(
            self.config.workflow_type,
            self._start_payload(conversation_id, proposal, workflow_id),
            id=workflow_id,
            task_queue=self.config.task_queue,
        )
        return await self._query_current_goal(handle, workflow_id=workflow_id)

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        client = await self._client_instance()
        workflow_id = self._workflow_id_for_goal(goal_id)
        handle = client.get_workflow_handle(workflow_id)
        current_payload = await self._wait_for_goal_payload(
            handle,
            workflow_id=workflow_id,
        )
        current_goal = self._goal_from_payload(current_payload, workflow_id)
        if current_goal.status in {"completed", "failed", "cancelled"}:
            return self._accept_goal(current_goal)
        signal_payload: dict[str, Any] = {"goal_id": goal_id}
        actor_payload = self._current_actor_payload()
        if actor_payload is not None:
            signal_payload["actor"] = actor_payload
        await handle.signal(self.config.resume_signal, signal_payload)
        return await self._query_current_goal(
            handle,
            workflow_id=workflow_id,
            previous_fingerprint=self._payload_fingerprint(current_payload),
        )

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        if self._checkpoint_provider is None:
            raise RuntimeError(
                "Temporal checkpoint provider is not configured. "
                "Pass a provider that reads AgentGoal state from the domain store."
            )
        return self._checkpoint_provider(goal_id)

    def _workflow_id_for_goal(self, goal_id: str) -> str:
        if self._workflow_id_provider is not None:
            workflow_id = self._workflow_id_provider(goal_id)
            if workflow_id:
                return workflow_id
        return f"{self.config.workflow_id_prefix}-{goal_id}"

    async def _client_instance(self) -> TemporalClientLike:
        if self._client is None:
            self._client = await self._client_factory(self.config)
        return self._client

    async def _query_current_goal(
        self,
        handle: TemporalWorkflowHandleLike,
        *,
        workflow_id: str,
        previous_fingerprint: str | None = None,
    ) -> AgentGoal:
        payload = await self._wait_for_goal_payload(
            handle,
            workflow_id=workflow_id,
            previous_fingerprint=previous_fingerprint,
        )
        return self._accept_goal(self._goal_from_payload(payload, workflow_id))

    async def _wait_for_goal_payload(
        self,
        handle: TemporalWorkflowHandleLike,
        *,
        workflow_id: str,
        previous_fingerprint: str | None = None,
    ) -> AgentGoal | dict[str, Any]:
        deadline = monotonic() + self.config.query_timeout_seconds
        last_error: Exception | None = None
        while True:
            try:
                payload = await handle.query(self.config.current_goal_query)
                if self._is_goal_payload(payload):
                    fingerprint = self._payload_fingerprint(payload)
                    if previous_fingerprint is None or fingerprint != previous_fingerprint:
                        return payload
            except Exception as exc:  # Temporal query availability is eventually consistent.
                last_error = exc

            if monotonic() >= deadline:
                detail = f" Last query error: {last_error}" if last_error else ""
                state_requirement = (
                    "a changed AgentGoal state"
                    if previous_fingerprint is not None
                    else "the initial AgentGoal state"
                )
                raise TimeoutError(
                    f"Timed out after {self.config.query_timeout_seconds:g}s waiting for "
                    f"{state_requirement} from Temporal workflow {workflow_id}.{detail}"
                )
            await asyncio.sleep(self.config.query_poll_interval_seconds)

    @staticmethod
    def _is_goal_payload(payload: Any) -> bool:
        if isinstance(payload, AgentGoal):
            return bool(payload.id)
        return isinstance(payload, dict) and bool(payload.get("id"))

    @staticmethod
    def _payload_fingerprint(payload: AgentGoal | dict[str, Any]) -> str:
        serializable = payload.model_dump(mode="json") if isinstance(payload, AgentGoal) else payload
        return json.dumps(serializable, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _goal_from_payload(payload: AgentGoal | dict[str, Any], workflow_id: str) -> AgentGoal:
        if isinstance(payload, AgentGoal):
            goal = payload
        elif isinstance(payload, dict):
            goal = AgentGoal(**payload)
        else:
            raise RuntimeError(
                f"Temporal workflow {workflow_id} returned an unsupported current goal payload: "
                f"{type(payload).__name__}."
            )
        if not goal.workflow_id:
            goal.workflow_id = workflow_id
        return goal

    def _accept_goal(self, goal: AgentGoal) -> AgentGoal:
        if self._goal_state_sink is not None:
            self._goal_state_sink(goal)
        return goal

    @staticmethod
    def _start_payload(conversation_id: str, proposal: AgentGoalProposal, workflow_id: str) -> dict[str, Any]:
        payload = {
            "conversation_id": conversation_id,
            "proposal": asdict(proposal),
            "workflow_id": workflow_id,
        }
        actor_payload = TemporalClientWorkflowGateway._current_actor_payload()
        if actor_payload is not None:
            payload["actor"] = actor_payload
        return payload

    @staticmethod
    def _current_actor_payload() -> dict[str, Any] | None:
        actor = current_actor()
        if actor is None:
            return None
        return {
            "user": actor.user.model_dump(mode="json"),
            "request_id": actor.request_id,
        }

    @staticmethod
    async def _default_client_factory(config: TemporalGatewayConfig) -> TemporalClientLike:
        try:
            from temporalio.client import Client
        except ImportError as exc:
            raise RuntimeError(
                "Temporal workflow runtime is selected, but the temporalio package is not installed. "
                "Install apps/api/requirements.txt or set NASUS_AGENT_WORKFLOW_RUNTIME=local."
            ) from exc
        return await Client.connect(config.address, namespace=config.namespace)
