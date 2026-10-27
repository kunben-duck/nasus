"""Actual Temporal workers, PG facts and LangGraph checkpoints; no target execution."""
import asyncio
import os
from uuid import uuid4

import pytest
from temporalio.client import Client, WorkflowFailureError
from temporalio.worker import Replayer, Worker

from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import AgentGoalWorkflowActivityService, build_agent_goal_activity_definitions
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import acting, replace_graph
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires an explicitly enabled local Temporal server")
def test_real_temporal_worker_restart_and_activity_retry_keep_the_original_resume_checkpoint(evidence_api, monkeypatch):
    v = evidence_api
    replace_graph(monkeypatch, "langgraph_postgres")
    assembly = get_runtime_assembly()
    workflow_state = assembly.agent_application_ports.workflow_state
    activities = AgentWorkflowActivityApplicationService(loop_runtime=assembly.agent_loop_runtime,
        goal_projector=assembly.agent_goal_projection)
    service = AgentGoalWorkflowActivityService(activity_application_provider=lambda: activities)
    definitions = build_agent_goal_activity_definitions(service)
    fixed = request(v)
    proposal = AgentGoalProposal(goal_template="system_image_build", title="Temporal fixed-source investigation",
        summary="Continue one original goal after a worker restart", target_refs=[f"build_plan:{fixed['plan_id']}"],
        goal_description="Investigate the pinned structural candidate without publishing or executing target code",
        planned_tools=[ToolPlanStep("system_image.build.structure", fixed)])
    original_update = LocalAgentGraphRuntime._update_goal
    crashes = []

    async def crash_once(self, goal, *, patch, expected_resume=None):
        await original_update(self, goal, patch=patch, expected_resume=expected_resume)
        if patch.get("resume_mode") == "structural_candidate_investigation" and not crashes:
            crashes.append(expected_resume.digest)
            raise RuntimeError("injected activity failure after atomic resume consumption")

    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", crash_once)

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-test-resume-" + uuid4().hex, query_timeout_seconds=60)

        async def factory(_):
            return client

        gateway = TemporalClientWorkflowGateway(config, client_factory=factory,
            workflow_id_provider=workflow_state.workflow_id_for_goal, goal_state_reader=workflow_state.get_goal,
            resume_replay_reader=workflow_state.is_resume_consumed)
        handle = None
        try:
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    started = await gateway.start_goal(v["conversation"].json()["id"], proposal)
                    handle = client.get_workflow_handle(started.workflow_id)
                    assert started.pause_reason == "waiting_confirmation"
                    structural = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(started.model_dump(mode="json")))
                    assert structural.pause_reason == "structural_candidate_review"
            replace_graph(monkeypatch, "langgraph_postgres")
            pin = AgentResumeCheckpoint.capture(structural.model_dump(mode="json"))
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    pending = await gateway.resume_goal(started.id, expected_resume=pin)
                    assert pending.pause_reason == "waiting_confirmation"
                    assert crashes == [pin.digest] and workflow_state.is_resume_consumed(pin)
                    blocked = acting(pending.model_dump(mode="json"))[-1]
                    assert blocked["selected_tool_id"] == "system_image.build.investigate"
                    await handle.signal(config.resume_signal, {"goal_id": started.id, "expected_resume": pin.payload()})
                    # A duplicate signal is delivered to the real workflow;
                    # its old pin cannot release the independent new gate.
                    await asyncio.sleep(.3)
                    assert workflow_state.get_goal(started.id) == pending
                    stale = pending.model_copy(deep=True)
                    stale.max_steps += 1
                    with pytest.raises(AgentResumeCheckpointChanged):
                        await gateway.resume_goal(started.id,
                            expected_resume=AgentResumeCheckpoint.capture(stale.model_dump(mode="json")))
                    # Model a concurrent PG change after a request was queued.
                    queued = AgentResumeCheckpoint.capture(pending.model_dump(mode="json"))
                    changed = pending.model_copy(deep=True)
                    changed.max_steps += 1
                    ConversationRepository().upsert_goal(changed)
                    await handle.signal(config.resume_signal, {"goal_id": started.id, "expected_resume": queued.payload(),
                        "actor": {"user": v["owner"]}})
                    for _ in range(200):
                        cursor = await handle.query(config.current_goal_query)
                        if cursor.get("_resume_error") == "agent_checkpoint_changed":
                            break
                        await asyncio.sleep(.05)
                    else:
                        pytest.fail("The actual worker did not reject the queued stale checkpoint")
                    assert workflow_state.get_goal(started.id) == changed
                    await handle.signal(config.resume_signal, {"goal_id": started.id, "actor": {"user": v["owner"]}})
                    for _ in range(200):
                        cursor = await handle.query(config.current_goal_query)
                        if cursor.get("_resume_error") == "agent_checkpoint_invalid":
                            break
                        await asyncio.sleep(.05)
                    else:
                        pytest.fail("A bare signal bypassed the fixed image goal precondition")
                    assert workflow_state.get_goal(started.id) == changed
                    final = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(changed.model_dump(mode="json")))
                    assert final.pause_reason == "build_completion_review"
                    assert final.max_steps == changed.max_steps
                    assert await gateway.resume_goal(started.id, expected_resume=pin) == final
                    assert final.model_calls_used == 0
                history = await handle.fetch_history()
            replay = await Replayer(workflows=[NasusAgentGoalWorkflow]).replay_workflow(history)
            assert replay.replay_failure is None
        finally:
            if handle is not None:
                await handle.cancel()
                async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                    with pytest.raises(WorkflowFailureError):
                        await asyncio.wait_for(handle.result(), 15)

    asyncio.run(verify())
