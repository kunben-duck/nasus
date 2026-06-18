from __future__ import annotations

from dataclasses import asdict
from typing import Any, Awaitable, Callable, Optional, Protocol
from uuid import uuid4

from .agent_goal_state_machine import AgentGoalRuntimeCheckpoint
from .agent_runtime_config import TemporalGatewayConfig, temporal_gateway_config_from_env
from .agent_runtime_models import AgentGoalProposal
from .models import AgentGoal


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
        await handle.signal(self.config.resume_signal, {"goal_id": goal_id})
        return await self._query_current_goal(handle, workflow_id=workflow_id)

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

    async def _query_current_goal(self, handle: TemporalWorkflowHandleLike, *, workflow_id: str) -> AgentGoal:
        payload = await handle.query(self.config.current_goal_query)
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
        if self._goal_state_sink is not None:
            self._goal_state_sink(goal)
        return goal

    @staticmethod
    def _start_payload(conversation_id: str, proposal: AgentGoalProposal, workflow_id: str) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "proposal": asdict(proposal),
            "workflow_id": workflow_id,
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
