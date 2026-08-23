from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, ContextManager

from ...application.agent.agent_models import AgentGoal
from ...application.agent.activities import AgentWorkflowActivityApplicationService
from ...application.platform.account_models import UserProfile
from ...application.platform.actor_context import actor_scope
from ..config.agent_runtime_config import TemporalGatewayConfig, temporal_gateway_config_from_env
from ..config.runtime_config import validate_runtime_configuration
from ...domain.agent.runtime_models import agent_goal_proposal_from_payload
from .nasus_agent_goal_workflow import (
    AGENT_GOAL_WORKFLOW_TYPE,
    CURRENT_GOAL_QUERY,
    NasusAgentGoalWorkflow,
    RESUME_GOAL_SIGNAL,
)


AgentWorkflowActivityProvider = Callable[[], AgentWorkflowActivityApplicationService]


def default_activity_application_provider() -> AgentWorkflowActivityApplicationService:
    from ...bootstrap import get_application_container

    return get_application_container().agent_workflow_activities


@dataclass
class AgentGoalWorkflowActivityService:
    """Activity boundary used by the Temporal AgentGoal workflow.

    Activities intentionally call AgentLoopRuntime directly instead of
    AgentService, because the workflow itself already owns the durable
    lifecycle. This prevents recursive Temporal workflow starts while keeping
    every action inside ToolInvocationRuntime.
    """

    activity_application_provider: AgentWorkflowActivityProvider = (
        default_activity_application_provider
    )

    async def start_agent_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._actor_scope(payload):
            application = self.activity_application_provider()
            proposal = agent_goal_proposal_from_payload(dict(payload["proposal"]))
            raw_workflow_id = payload.get("workflow_id")
            goal = await application.start_goal(
                conversation_id=str(payload["conversation_id"]),
                proposal=proposal,
                workflow_id=str(raw_workflow_id) if raw_workflow_id else None,
            )
            return self._serialize_goal(goal)

    async def resume_agent_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._actor_scope(payload):
            application = self.activity_application_provider()
            goal = await application.resume_goal(str(payload["goal_id"]))
            return self._serialize_goal(goal)

    @staticmethod
    def _serialize_goal(goal: AgentGoal) -> dict[str, Any]:
        return goal.model_dump()

    @staticmethod
    def _actor_scope(payload: dict[str, Any]) -> ContextManager[Any]:
        actor_payload = payload.get("actor")
        if not isinstance(actor_payload, dict):
            return nullcontext()
        user_payload = actor_payload.get("user")
        if not isinstance(user_payload, dict):
            return nullcontext()
        request_id = actor_payload.get("request_id")
        return actor_scope(
            UserProfile(**user_payload),
            request_id=str(request_id) if request_id is not None else None,
        )


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
    resolved_config = config or temporal_gateway_config_from_env()
    configured_protocol = {
        "workflow_type": resolved_config.workflow_type,
        "current_goal_query": resolved_config.current_goal_query,
        "resume_signal": resolved_config.resume_signal,
    }
    canonical_protocol = {
        "workflow_type": AGENT_GOAL_WORKFLOW_TYPE,
        "current_goal_query": CURRENT_GOAL_QUERY,
        "resume_signal": RESUME_GOAL_SIGNAL,
    }
    mismatches = [
        f"{name}={configured_protocol[name]!r} (expected {expected!r})"
        for name, expected in canonical_protocol.items()
        if configured_protocol[name] != expected
    ]
    if mismatches:
        raise RuntimeError(
            "Temporal AgentGoal protocol names are fixed for API/worker compatibility: "
            + ", ".join(mismatches)
        )
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
        max_concurrent_activities=resolved_config.max_concurrent_activities,
    )
    await worker.run()


def main() -> None:
    validate_runtime_configuration()
    asyncio.run(run_temporal_agent_goal_worker())


if __name__ == "__main__":
    main()


__all__ = [
    "AgentGoalWorkflowActivityService",
    "build_nasus_agent_goal_workflow",
    "build_temporal_activity_definitions",
    "run_temporal_agent_goal_worker",
]
