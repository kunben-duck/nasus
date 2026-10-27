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
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged, InvalidAgentResumeCheckpoint
from ...domain.agent.goal_creation import ActiveAgentGoalExists, AgentGoalStartRecoveryRequired
from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from .nasus_agent_goal_workflow import (
    AGENT_GOAL_WORKFLOW_TYPE,
    CURRENT_GOAL_QUERY,
    NasusAgentGoalWorkflow,
    RESUME_GOAL_SIGNAL,
)
from .nasus_conversation_turn_workflow import NasusConversationTurnWorkflow
from .nasus_context_retrieval_workflow import NasusContextRetrievalWorkflow
from .context_retrieval_runtime import TemporalContextRetrievalRuntime, build_context_retrieval_activities, reconcile_context_retrievals
from .nasus_generation_workflow import NasusTestDesignGenerationWorkflow
from .generation_runtime import TemporalGenerationRuntime, build_generation_activities, reconcile_generation_jobs
from .nasus_structure_workflow import NasusStructureBuildWorkflow
from .structure_runtime import TemporalStructureRuntime, build_structure_activities, reconcile_structure_jobs
from .nasus_native_build_workflow import NasusNativeBuildWorkflow
from .native_build_runtime import TemporalNativeBuildRuntime, build_native_build_activities, reconcile_native_builds
from .nasus_http_fixture_workflow import NasusHttpFixtureWorkflow
from .http_fixture_runtime import TemporalHttpFixtureRuntime, build_http_fixture_activities, reconcile_http_fixtures
from .nasus_run_plan_case_workflow import NasusRunPlanCaseWorkflow
from .run_plan_case_runtime import TemporalRunPlanCaseRuntime, build_run_plan_case_activities, reconcile_run_plan_cases
from ...application.agent.turns import ConversationTurnExecutionRequest


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
            try:
                goal = await application.start_goal(
                    conversation_id=str(payload["conversation_id"]),
                    proposal=proposal,
                    workflow_id=str(raw_workflow_id) if raw_workflow_id else None,
                )
            except ActiveAgentGoalExists as conflict:
                return {"_start_error": "active_agent_goal_exists", "goal_id": conflict.goal_id}
            except AgentGoalStartRecoveryRequired as recovery:
                return {"_start_error": "agent_start_recovery_required", "goal_id": recovery.goal_id}
            except AgentPlanPolicyViolation as rejected:
                return {"_start_error": rejected.code}
            return self._serialize_goal(goal)

    async def resume_agent_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._actor_scope(payload):
            application = self.activity_application_provider()
            expected = payload.get("expected_resume")
            try:
                if expected is not None:
                    checkpoint = AgentResumeCheckpoint.from_payload(expected)
                    if checkpoint.goal_id != payload["goal_id"]:
                        raise AgentResumeCheckpointChanged()
                    goal = await application.resume_goal(str(payload["goal_id"]), expected_resume=checkpoint)
                else:
                    goal = await application.resume_goal(str(payload["goal_id"]))
            except (AgentResumeCheckpointChanged, InvalidAgentResumeCheckpoint) as exc:
                goal = application.get_goal(str(payload["goal_id"]))
                return {**self._serialize_goal(goal), "_resume_error":
                    "agent_checkpoint_changed" if isinstance(exc, AgentResumeCheckpointChanged) else "agent_checkpoint_invalid"}
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


def build_agent_goal_activity_definitions(
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
        if payload.get("workflow_id") != activity.info().workflow_id:
            return {"_start_error": "agent_start_scope_changed"}
        return await service.start_agent_goal(payload)

    @activity.defn(name="resume_agent_goal")
    async def resume_agent_goal(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.resume_agent_goal(payload)

    return [start_agent_goal, resume_agent_goal]


def build_conversation_turn_activity_definitions() -> list[Callable[..., Any]]:
    try:
        from temporalio import activity
    except ImportError as exc:
        raise RuntimeError(
            "Temporal worker requires the temporalio package. "
            "Install apps/api/requirements.txt before starting workflow-service."
        ) from exc

    @activity.defn(name="run_conversation_turn")
    async def run_conversation_turn(payload: dict[str, Any]) -> dict[str, Any]:
        from ...bootstrap import get_application_container

        request = ConversationTurnExecutionRequest.from_payload(payload)
        stop_heartbeat = asyncio.Event()

        async def heartbeat() -> None:
            while not stop_heartbeat.is_set():
                activity.heartbeat({"turn_id": request.turn_id})
                try:
                    await asyncio.wait_for(stop_heartbeat.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            application = get_application_container().conversation_turns
            if request.actor is not None:
                with actor_scope(request.actor, request_id=request.request_id):
                    turn = await application.execute_turn(request)
            else:
                turn = await application.execute_turn(request)
            return turn.model_dump()
        finally:
            stop_heartbeat.set()
            await heartbeat_task

    return [run_conversation_turn]


def build_temporal_activity_definitions(
    activity_service: AgentGoalWorkflowActivityService | None = None,
) -> list[Callable[..., Any]]:
    return [
        *build_agent_goal_activity_definitions(activity_service),
        *build_conversation_turn_activity_definitions(),
    ]


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
    goal_worker = Worker(
        client,
        task_queue=resolved_config.task_queue,
        workflows=[build_nasus_agent_goal_workflow(resolved_config)],
        activities=build_agent_goal_activity_definitions(),
        max_concurrent_activities=resolved_config.max_concurrent_activities,
    )
    conversation_turn_worker = Worker(
        client,
        task_queue=resolved_config.resolved_conversation_turn_task_queue,
        workflows=[NasusConversationTurnWorkflow],
        activities=build_conversation_turn_activity_definitions(),
        max_concurrent_activities=resolved_config.max_concurrent_activities,
    )
    context_runtime = TemporalContextRetrievalRuntime(resolved_config, client)
    context_worker = Worker(client, task_queue=context_runtime.task_queue, workflows=[NasusContextRetrievalWorkflow],
        activities=build_context_retrieval_activities(), max_concurrent_activities=resolved_config.max_concurrent_activities)
    generation_runtime = TemporalGenerationRuntime(resolved_config, client)
    generation_worker = Worker(client, task_queue=generation_runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow],
        activities=build_generation_activities(), max_concurrent_activities=resolved_config.max_concurrent_activities)
    structure_runtime = TemporalStructureRuntime(resolved_config, client)
    structure_worker = Worker(client, task_queue=structure_runtime.task_queue, workflows=[NasusStructureBuildWorkflow],
        activities=build_structure_activities(), max_concurrent_activities=1)
    native_runtime = TemporalNativeBuildRuntime(resolved_config, client)
    native_worker = Worker(client, task_queue=native_runtime.task_queue, workflows=[NasusNativeBuildWorkflow],
        activities=build_native_build_activities(), max_concurrent_activities=1)
    fixture_runtime = TemporalHttpFixtureRuntime(resolved_config, client)
    fixture_worker = Worker(client, task_queue=fixture_runtime.task_queue, workflows=[NasusHttpFixtureWorkflow],
        activities=build_http_fixture_activities(), max_concurrent_activities=1)
    case_runtime = TemporalRunPlanCaseRuntime(resolved_config, client)
    case_worker = Worker(client, task_queue=case_runtime.task_queue, workflows=[NasusRunPlanCaseWorkflow],
        activities=build_run_plan_case_activities(), max_concurrent_activities=1)
    await asyncio.gather(goal_worker.run(), conversation_turn_worker.run(), context_worker.run(), generation_worker.run(), structure_worker.run(), native_worker.run(), fixture_worker.run(), case_worker.run(),
        reconcile_context_retrievals(context_runtime), reconcile_generation_jobs(generation_runtime), reconcile_structure_jobs(structure_runtime),
        reconcile_native_builds(native_runtime), reconcile_http_fixtures(fixture_runtime), reconcile_run_plan_cases(case_runtime))


def main() -> None:
    validate_runtime_configuration()
    asyncio.run(run_temporal_agent_goal_worker())


if __name__ == "__main__":
    main()


__all__ = [
    "AgentGoalWorkflowActivityService",
    "build_agent_goal_activity_definitions",
    "build_conversation_turn_activity_definitions",
    "build_nasus_agent_goal_workflow",
    "build_temporal_activity_definitions",
    "run_temporal_agent_goal_worker",
]
