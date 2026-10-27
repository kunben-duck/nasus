"""Real Temporal start/retry and worker replacement for a naturally prepared goal."""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.persistence.agent_start_models import AgentGoalStartReceiptRecord
from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import AgentGoalWorkflowActivityService, build_agent_goal_activity_definitions
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import replace_graph
from apps.api.tests.test_agent_start_receipts_temporal import close_handles
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_natural_build_entries_api import require_prepared
from apps.api.tests.test_source_build_wait_api import fresh_project, capture_code, count


pytestmark = pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicitly enabled local Temporal")


@pytest.mark.parametrize("retry", [False, True], ids=["worker-replacement", "start-activity-retry"])
@pytest.mark.parametrize("missing_code", [False, True], ids=["captured", "waiting-inputs"])
def test_natural_preparation_keeps_original_sources_and_distinct_gates_across_real_workers(evidence_api, monkeypatch, retry, missing_code):
    v = fresh_project(evidence_api) if missing_code else evidence_api
    replace_graph(monkeypatch, "langgraph_postgres")
    assembly = get_runtime_assembly()
    state = assembly.agent_application_ports.workflow_state
    with actor_scope(UserProfile.model_validate(v["owner"])):
        conversation = assembly.agent_application_ports.loop_state.get_conversation(v["conversation"].json()["id"])
        message = "基于代码、需求文档和测试用例构建当前项目的系统画像。" if missing_code else "Build the official system image from code, US docs, and tests"
        proposal = assembly.saved_build_intents.plan(conversation, message).agent_goal
    activities = AgentWorkflowActivityApplicationService(loop_runtime=assembly.agent_loop_runtime,
        goal_projector=assembly.agent_goal_projection)
    service = AgentGoalWorkflowActivityService(activity_application_provider=lambda: activities)
    definitions = build_agent_goal_activity_definitions(service)
    graph = assembly.agent_loop_runtime.graph_runtime
    original_start, starts = graph.start, []

    async def observe_start(goal_id, request):
        starts.append(goal_id)
        await original_start(goal_id, request)
        if retry:
            raise RuntimeError("injected loss after canonical preparation and independent budget gate")

    monkeypatch.setattr(graph, "start", observe_start)

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-natural-build-" + uuid4().hex, query_timeout_seconds=60)

        async def factory(_):
            return client

        gateway = TemporalClientWorkflowGateway(config, client_factory=factory,
            workflow_id_provider=state.workflow_id_for_goal, goal_state_reader=state.get_goal,
            resume_replay_reader=state.is_resume_consumed)
        handles = []
        try:
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    started = await gateway.start_goal(conversation.id, proposal)
                    handles.append(client.get_workflow_handle(started.workflow_id))
                if missing_code:
                    initial = started.model_dump(mode="json")
                    assert initial["pause_reason"] == "missing_captured_code"
                    assert count(BuildPlanRecord, v["project_id"]) == count(BuildAuthorizationRecord, v["project_id"]) == 0
                else:
                    initial, fixed = require_prepared(v, {"agent_goals": [started.model_dump(mode="json")]})
                assert initial["active_runtime_ms"] >= 0 and initial["active_started_at"] is None
                assert starts == [started.id]
                with session_scope() as session:
                    receipt = session.scalar(select(AgentGoalStartReceiptRecord).where(
                        AgentGoalStartReceiptRecord.goal_id == started.id))
                    assert receipt.workflow_id == started.workflow_id
            if missing_code:
                capture_code(v, v["path"])
                v["image"] = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
            v["path"].unlink()
            replace_graph(monkeypatch, "langgraph_postgres")
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    if missing_code:
                        captured = await gateway.resume_goal(started.id,
                            expected_resume=AgentResumeCheckpoint.capture(initial))
                        assert captured.id == started.id and captured.pause_reason == "waiting_confirmation"
                        assert captured.started_at == initial["started_at"] and captured.active_runtime_ms >= initial["active_runtime_ms"]
                        assert captured.active_started_at is None
                        assert await gateway.resume_goal(started.id, expected_resume=AgentResumeCheckpoint.capture(initial)) == captured
                        assert count(BuildAuthorizationRecord, v["project_id"]) == 0
                        initial, fixed = require_prepared(v, {"agent_goals": [captured.model_dump(mode="json")]}, waited=True)
                    built = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(initial))
                    assert built.pause_reason == "structural_candidate_review"
                    assert built.active_started_at is None and built.active_runtime_ms >= initial["active_runtime_ms"]
                    prefix = built.model_dump(mode="json")["steps"]
                    structure_index = next(index for index, step in enumerate(prefix)
                        if step["selected_tool_id"] == "system_image.build.structure")
                    fixed_steps = prefix[:structure_index]

                    def require_original_commands(value):
                        current = value.model_dump(mode="json")["steps"]
                        assert current[:len(fixed_steps)] == fixed_steps
                        for original in prefix:
                            if original["phase"] != "acting":
                                continue
                            saved = next(step for step in current if step["id"] == original["id"])
                            assert saved["selected_tool_id"] == original["selected_tool_id"]
                            assert saved["tool_input_payload"] == original["tool_input_payload"]
                            assert saved["tool_invocation_id"] == original["tool_invocation_id"]
                            assert saved["status"] == "completed"

                    pending = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(built.model_dump(mode="json")))
                    assert pending.pause_reason == "waiting_confirmation"
                    assert pending.active_started_at is None and pending.active_runtime_ms >= built.active_runtime_ms
                    require_original_commands(pending)
                    # The earlier structure confirmation cannot release investigation.
                    assert await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(built.model_dump(mode="json"))) == pending
                    assert state.get_goal(started.id) == pending
            replace_graph(monkeypatch, "langgraph_postgres")
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    final = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(pending.model_dump(mode="json")))
                    assert final.id == started.id and final.pause_reason == "build_completion_review"
                    assert final.started_at == initial["started_at"] and final.active_runtime_ms >= pending.active_runtime_ms
                    assert final.active_started_at is None
                    assert final.model_calls_used == 0
                    require_original_commands(final)
                    with session_scope() as session:
                        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(
                            BuildPlanRecord.project_id == v["project_id"])) == 1
                        grants = session.scalars(select(BuildAuthorizationRecord).where(
                            BuildAuthorizationRecord.goal_id == started.id)).all()
                        assert len(grants) == 1 and grants[0].plan_id == fixed["plan_id"]
                replay = await Replayer(workflows=[NasusAgentGoalWorkflow]).replay_workflow(await handles[0].fetch_history())
                assert replay.replay_failure is None
        finally:
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                await close_handles(handles)

    asyncio.run(verify())
