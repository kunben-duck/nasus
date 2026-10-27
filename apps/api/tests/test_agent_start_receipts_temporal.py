"""Actual Temporal start conflicts and retries with PG facts, not cursor writes."""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.worker import Worker, Replayer
from temporalio.service import RPCError

from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.agent.lifecycle import AgentGoalLifecycleApplicationService
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.persistence.agent_start_models import AgentGoalStartReceiptRecord
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import AgentGoalWorkflowActivityService, build_agent_goal_activity_definitions
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import replace_graph
from apps.api.tests.test_build_plan_api import submit
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_targeted_build_intent_api import fixed_request

pytestmark = pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicitly enabled local Temporal")


def proposal(v, fixed):
    return AgentGoalProposal(goal_template="system_image_build", title="Durable saved intent", summary="Original inputs",
        goal_description="Build the fixed target without transferring execution consent", target_refs=[f"project:{v['project_id']}",
            f"build_plan:{fixed['plan_id']}", f"build_plan_digest:{fixed['plan_digest']}"])


def require_single_controller(v, state):
    with session_scope() as session:
        goals = session.scalars(select(AgentGoalRecord).where(AgentGoalRecord.conversation_id == v["conversation"].json()["id"])).all()
        assert len(goals) == 1
        goal = state.get_goal(goals[0].id)
        receipts = session.scalars(select(AgentGoalStartReceiptRecord).where(
            AgentGoalStartReceiptRecord.conversation_id == goal.conversation_id)).all()
        assert len(receipts) == 1 and receipts[0].goal_id == goal.id and receipts[0].workflow_id == goal.workflow_id
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal.id)) == 0
    return goal


async def close_handles(handles):
    for handle in handles:
        if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(handle.result(), 15)


@pytest.mark.parametrize("different", [False, True], ids=["same-plan", "different-plan"])
def test_actual_temporal_concurrent_starts_keep_the_original_controller(evidence_api, monkeypatch, different):
    v = evidence_api
    replace_graph(monkeypatch, "langgraph_postgres")
    assembly = get_runtime_assembly()
    state = assembly.agent_application_ports.workflow_state
    fixed, original = fixed_request(v)
    other = fixed
    if different:
        command = submit(v, target=original["proposal"]["intent"]["target"], objective="A different concurrent Temporal intent").json()
        assert command["status"] == "completed"
        plan_id = command["result"]["object_refs"][0].split(":", 1)[1]
        detail = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{plan_id}", headers=v["headers"]).json()
        other = {**fixed, "plan_id": plan_id, "plan_digest": detail["plan_digest"]}
    activities = AgentWorkflowActivityApplicationService(loop_runtime=assembly.agent_loop_runtime, goal_projector=assembly.agent_goal_projection)
    service = AgentGoalWorkflowActivityService(activity_application_provider=lambda: activities)
    graph = assembly.agent_loop_runtime.graph_runtime
    original_start, starts = graph.start, []

    async def observe_start(goal_id, planned):
        starts.append(goal_id)
        return await original_start(goal_id, planned)

    monkeypatch.setattr(graph, "start", observe_start)

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        config = TemporalGatewayConfig(task_queue="nasus-start-race-" + uuid4().hex, query_timeout_seconds=30)
        handles = []

        class ClientProxy:
            async def start_workflow(self, *args, **kwargs):
                handle = await client.start_workflow(*args, **kwargs)
                handles.append(handle)
                return handle

        async def factory(_):
            return ClientProxy()

        gateway = TemporalClientWorkflowGateway(config, client_factory=factory, goal_state_reader=state.get_goal)
        lifecycle = AgentGoalLifecycleApplicationService(assembly.agent_application_ports.goal_lifecycle, gateway,
            build_intents=assembly.agent_service.build_intents)
        monkeypatch.setattr(lifecycle, "active_goal_for_conversation", lambda _: None)
        async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow],
                activities=build_agent_goal_activity_definitions(service)):
            try:
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    results = await asyncio.gather(*(lifecycle.start_from_proposal(v["conversation"].json()["id"], proposal(v, item))
                        for item in (fixed, other)), return_exceptions=True)
                errors = [item for item in results if isinstance(item, Exception)]
                if different:
                    assert len(errors) == 1 and isinstance(errors[0], AgentPlanPolicyViolation)
                    assert errors[0].code == "saved_build_intent_active_goal_changed"
                else:
                    assert errors == [] and len({item.id for item in results}) == 1
                goal = require_single_controller(v, state)
                assert starts == [goal.id] and goal.pause_reason == "waiting_confirmation"
                loser, = [handle for handle in handles if handle.id != goal.workflow_id]
                assert await asyncio.wait_for(loser.result(), 10) == {"_start_error": "active_agent_goal_exists", "goal_id": goal.id}
                with pytest.raises(RPCError, match="workflow execution already completed"):
                    await loser.signal("resume_goal", {"goal_id": goal.id})
                assert state.get_goal(goal.id) == goal
                for handle in handles:
                    result = await Replayer(workflows=[NasusAgentGoalWorkflow]).replay_workflow(await handle.fetch_history())
                    assert result.replay_failure is None
            finally:
                await close_handles(handles)

    asyncio.run(verify())


@pytest.mark.parametrize("when", ["after-pause", "before-graph"], ids=["replay-readonly", "recovery-required"])
def test_actual_start_activity_retry_does_not_create_or_confirm_another_goal(evidence_api, monkeypatch, when):
    v = evidence_api
    replace_graph(monkeypatch, "langgraph_postgres")
    assembly = get_runtime_assembly()
    state = assembly.agent_application_ports.workflow_state
    fixed, _ = fixed_request(v)
    activities = AgentWorkflowActivityApplicationService(loop_runtime=assembly.agent_loop_runtime, goal_projector=assembly.agent_goal_projection)
    graph = assembly.agent_loop_runtime.graph_runtime
    original_start, starts = graph.start, []

    async def interrupted_start(goal_id, planned):
        starts.append(goal_id)
        if when == "before-graph":
            raise RuntimeError("injected failure after durable creation, before graph execution")
        await original_start(goal_id, planned)
        raise RuntimeError("injected failure after the graph reached its independent gate")

    monkeypatch.setattr(graph, "start", interrupted_start)

    class ObservedActivity(AgentGoalWorkflowActivityService):
        attempts = 0

        async def start_agent_goal(self, payload):
            self.attempts += 1
            return await super().start_agent_goal(payload)

    service = ObservedActivity(activity_application_provider=lambda: activities)

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        config = TemporalGatewayConfig(task_queue="nasus-start-retry-" + uuid4().hex, query_timeout_seconds=30)
        handles = []

        class ClientProxy:
            async def start_workflow(self, *args, **kwargs):
                handle = await client.start_workflow(*args, **kwargs)
                handles.append(handle)
                return handle

        async def factory(_):
            return ClientProxy()

        gateway = TemporalClientWorkflowGateway(config, client_factory=factory, goal_state_reader=state.get_goal)
        async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow],
                activities=build_agent_goal_activity_definitions(service)):
            try:
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    if when == "before-graph":
                        with pytest.raises(AgentPlanPolicyViolation) as recovery:
                            await gateway.start_goal(v["conversation"].json()["id"], proposal(v, fixed))
                        assert recovery.value.code == "agent_start_recovery_required"
                    else:
                        started = await gateway.start_goal(v["conversation"].json()["id"], proposal(v, fixed))
                        assert started.pause_reason == "waiting_confirmation"
                goal = require_single_controller(v, state)
                assert service.attempts == 2 and starts == [goal.id]
                assert goal.status == ("pending" if when == "before-graph" else "paused")
                with session_scope() as session:
                    commands = session.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.conversation_id == goal.conversation_id)).all()
                    assert len([item for item in commands if item.tool_id == "query.system_image.build_plans.read"]) == (0 if when == "before-graph" else 1)
                    assert len([item for item in commands if item.tool_id == "system_image.build.authorize"]) == (0 if when == "before-graph" else 1)
                result = await Replayer(workflows=[NasusAgentGoalWorkflow]).replay_workflow(await handles[0].fetch_history())
                assert result.replay_failure is None
            finally:
                await close_handles(handles)

    asyncio.run(verify())


def test_actual_temporal_rejects_a_payload_that_spoofs_its_workflow_owner(evidence_api):
    from dataclasses import asdict
    from unittest.mock import AsyncMock

    v = evidence_api
    fixed, _ = fixed_request(v)
    application = type("NoStart", (), {"start_goal": AsyncMock()})()
    service = AgentGoalWorkflowActivityService(activity_application_provider=lambda: application)

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        task_queue = "nasus-start-owner-" + uuid4().hex
        workflow_id = "nasus-start-owner-workflow-" + uuid4().hex
        payload = {"conversation_id": v["conversation"].json()["id"], "workflow_id": "a-different-controller",
            "proposal": asdict(proposal(v, fixed))}
        async with Worker(client, task_queue=task_queue, workflows=[NasusAgentGoalWorkflow],
                activities=build_agent_goal_activity_definitions(service)):
            handle = await client.start_workflow("NasusAgentGoalWorkflow", payload, id=workflow_id, task_queue=task_queue)
            assert await asyncio.wait_for(handle.result(), 15) == {"_start_error": "agent_start_scope_changed"}
            application.start_goal.assert_not_awaited()
            result = await Replayer(workflows=[NasusAgentGoalWorkflow]).replay_workflow(await handle.fetch_history())
            assert result.replay_failure is None
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(AgentGoalRecord).where(
                AgentGoalRecord.conversation_id == payload["conversation_id"])) == 0
            assert session.scalar(select(func.count()).select_from(AgentGoalStartReceiptRecord).where(
                AgentGoalStartReceiptRecord.conversation_id == payload["conversation_id"])) == 0

    asyncio.run(verify())
