from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from .agent_runtime_config import TemporalGatewayConfig, temporal_gateway_config_from_env
from .agent_runtime_models import agent_goal_proposal_from_payload
from .models import AgentGoal


TERMINAL_AGENT_GOAL_STATUSES = {"completed", "failed", "cancelled"}
WAITING_AGENT_GOAL_STATUSES = {"paused", "blocked"}


ApplicationStoreProvider = Callable[[], Any]


def default_store_provider() -> Any:
    from .store import store

    return store


@dataclass
class AgentGoalWorkflowActivityService:
    """Activity boundary used by the Temporal AgentGoal workflow.

    Activities intentionally call AgentLoopRuntime directly instead of
    AgentService, because the workflow itself already owns the durable
    lifecycle. This prevents recursive Temporal workflow starts while keeping
    every action inside ToolInvocationRuntime.
    """

    store_provider: ApplicationStoreProvider = default_store_provider

    async def start_agent_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = self.store_provider()
        proposal = agent_goal_proposal_from_payload(dict(payload["proposal"]))
        goal = await store.agent_loop_runtime.start_goal(str(payload["conversation_id"]), proposal)
        workflow_id = payload.get("workflow_id")
        if workflow_id and not goal.workflow_id:
            goal.workflow_id = str(workflow_id)
            store.conversation_repository.upsert_goal(goal)
            store._upsert_goal_in_conversation(goal)
        return self._serialize_goal(goal)

    async def resume_agent_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = self.store_provider()
        goal = await store.agent_loop_runtime.resume_goal(str(payload["goal_id"]))
        return self._serialize_goal(goal)

    @staticmethod
    def _serialize_goal(goal: AgentGoal) -> dict[str, Any]:
        return goal.model_dump()


def build_temporal_activity_definitions(
    activity_service: AgentGoalWorkflowActivityService | None = None,
) -> list[Callable[..., Any]]:
    try:
        from temporalio import activity
    except ImportError as exc:
        raise RuntimeError(
            "Temporal worker requires the temporalio package. "
            "Install apps/api/requirements.txt before starting workflow-service."
        ) from exc

    service = activity_service or AgentGoalWorkflowActivityService()

    @activity.defn(name="start_agent_goal")
    async def start_agent_goal(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.start_agent_goal(payload)

    @activity.defn(name="resume_agent_goal")
    async def resume_agent_goal(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.resume_agent_goal(payload)

    return [start_agent_goal, resume_agent_goal]


def build_nasus_agent_goal_workflow(config: TemporalGatewayConfig | None = None):
    try:
        from temporalio import workflow
    except ImportError as exc:
        raise RuntimeError(
            "Temporal worker requires the temporalio package. "
            "Install apps/api/requirements.txt before starting workflow-service."
        ) from exc

    resolved_config = config or temporal_gateway_config_from_env()

    @workflow.defn(name=resolved_config.workflow_type)
    class NasusAgentGoalWorkflow:
        def __init__(self) -> None:
            self._current_goal: dict[str, Any] | None = None
            self._resume_requested = False

        @workflow.run
        async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
            self._current_goal = await workflow.execute_activity(
                "start_agent_goal",
                payload,
                start_to_close_timeout=timedelta(minutes=30),
            )
            while self._is_waiting_for_resume(self._current_goal):
                await workflow.wait_condition(lambda: self._resume_requested)
                self._resume_requested = False
                self._current_goal = await workflow.execute_activity(
                    "resume_agent_goal",
                    {"goal_id": self._current_goal["id"]},
                    start_to_close_timeout=timedelta(minutes=30),
                )
            return self._current_goal

        @workflow.query(name=resolved_config.current_goal_query)
        def current_goal(self) -> dict[str, Any]:
            return self._current_goal or {}

        @workflow.signal(name=resolved_config.resume_signal)
        async def resume_goal(self, payload: dict[str, Any] | None = None) -> None:
            self._resume_requested = True

        @staticmethod
        def _is_waiting_for_resume(goal: dict[str, Any] | None) -> bool:
            return bool(goal and goal.get("status") in WAITING_AGENT_GOAL_STATUSES)

    return NasusAgentGoalWorkflow


async def run_temporal_agent_goal_worker(config: TemporalGatewayConfig | None = None) -> None:
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except ImportError as exc:
        raise RuntimeError(
            "Temporal worker requires the temporalio package. "
            "Install apps/api/requirements.txt before starting workflow-service."
        ) from exc

    resolved_config = config or temporal_gateway_config_from_env()
    client = await Client.connect(resolved_config.address, namespace=resolved_config.namespace)
    worker = Worker(
        client,
        task_queue=resolved_config.task_queue,
        workflows=[build_nasus_agent_goal_workflow(resolved_config)],
        activities=build_temporal_activity_definitions(),
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_temporal_agent_goal_worker())


if __name__ == "__main__":
    main()
