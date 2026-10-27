"""Real PG/ToolRuntime batch lifecycle, with explicit HTTP fixtures, no external egress."""
import asyncio
import json
import os
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from apps.api.app.application.quality_loop.generation_execution_inputs import GENERATION_BATCH_PREVIEW_TOOL
from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_CANCEL_TOOL
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel
from apps.api.tests.test_generation_batch_results_api import aggregate, ledger, execution, design_scope, publication, documents, evidence_api, read
from apps.api.tests.test_generation_execution_api import queued, job, command
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm
from apps.api.tests.test_semantic_link_model import native_reply
from apps.api.tests.test_generation_batches import responses_for


@pytest.fixture
def formal_batches(aggregate, monkeypatch):
    v = aggregate
    monkeypatch.setattr(v["executor"], "batch_executor", v["batch_executor"])
    return v


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_confirmed_three_batch_command_uses_the_shared_worker_and_finishes_only_after_atomic_result(formal_batches):
    v = formal_batches
    preview = completed(invoke(v, GENERATION_BATCH_PREVIEW_TOOL, v["batch_selection"].model_dump(mode="json")))["result"]["test_design_execution_preview"]
    assert preview["request"] == v["batch_request"].model_dump(mode="json") and preview["call_count"] == 3
    assert "artifact_ref" not in str(preview) and "native-test-design-fixture-key" not in str(preview)
    assert not v["batch_native_sent"]
    ident = queued(v, payload=preview["request"])
    v["workflow"].start.assert_awaited_with(ident)
    assert command(v, ident).json()["status"] == "running"
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    result = job(v, ident)
    assert result["reply_archived"] and not result["provider_outcome_unknown"] and result["recovery_request"] is None
    progress = result["batch_progress"]
    assert progress["call_count"] == progress["claimed_calls"] == progress["archived_calls"] == 3
    assert progress["unknown_calls"] == progress["unstarted_calls"] == 0 and not progress["invoice_verified"]
    assert len(v["batch_native_sent"]) == 3 and not v["native_calls"]
    assert asyncio.run(v["jobs"].run(ident)) == "completed" and len(v["batch_native_sent"]) == 3
    response = read(v, {"generation_id": result["generation_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["batch_count"] == 3
    assert response.json()["result"]["proposal"]["coverage"]["passed_count"] == 0


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_second_batch_unknown_is_terminal_and_never_resends_or_commits_partial_draft(formal_batches, monkeypatch):
    v = formal_batches
    responses = dict(responses_for(v["batch_planned"].input, v["batch_planned"].plan))
    sent = []
    def handle(request):
        batch = json.loads(json.loads(request.content)["messages"][-1]["content"])
        sent.append(batch["batch_digest"])
        return httpx.Response(503) if len(sent) == 2 else httpx.Response(200, json=native_reply("openai_compatible", responses[batch["batch_digest"]]))
    monkeypatch.setattr(v["batch_executor"], "provider", HTTPTestDesignModel(transport=httpx.MockTransport(handle)))
    ident = queued(v, payload=v["batch_request"].model_dump(mode="json"))
    # The first infrastructure failure is retryable. Its claim is retained;
    # the next worker fails closed rather than repeating that native request.
    with pytest.raises(RuntimeError):
        asyncio.run(v["jobs"].run(ident))
    assert asyncio.run(v["jobs"].run(ident)) == "failed"
    result = job(v, ident)
    assert result["provider_outcome_unknown"] and not result["reply_archived"] and result["generation_id"] is None
    assert result["batch_progress"]["archived_calls"] == result["batch_progress"]["unknown_calls"] == result["batch_progress"]["unstarted_calls"] == 1
    assert result["recovery_request"] is None and len(sent) == 2 and not v["native_calls"]


def test_confirmed_cancellation_before_first_batch_blocks_the_shared_worker_without_egress(formal_batches):
    v = formal_batches
    ident = queued(v, payload=v["batch_request"].model_dump(mode="json"))
    pending = invoke(v, GENERATION_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}).json()
    completed(confirm(v, pending))
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled"
    assert job(v, ident)["generation_id"] is None and not v["batch_native_sent"] and not v["native_calls"]


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
@pytest.mark.parametrize("documents", [3], indirect=True)
def test_real_temporal_retries_three_batch_aggregate_commit_without_resending_native_calls(formal_batches, monkeypatch):
    from temporalio.client import Client
    from temporalio.worker import Replayer, Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.generation_runtime import TemporalGenerationRuntime, build_generation_activities
    from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
    v = formal_batches
    ident = queued(v, payload=v["batch_request"].model_dump(mode="json"))
    original, attempts = v["batch_results"].repository.record_batch, []
    def first_failure(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("private-batch-commit-fixture-must-not-enter-workflow-history")
        return original(*args, **kwargs)
    monkeypatch.setattr(v["batch_results"].repository, "record_batch", first_failure)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-batch-retry-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalGenerationRuntime(config, client)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow],
                activities=build_generation_activities()):
            assert await runtime.start(ident)
            handle = client.get_workflow_handle("nasus-test-design-generation:" + ident)
            assert await asyncio.wait_for(handle.result(), 300) == "completed"
            assert not await runtime.start(ident)
            history = await handle.fetch_history()
            scheduled = [event.activity_task_scheduled_event_attributes for event in history.events
                if event.HasField("activity_task_scheduled_event_attributes")]
            assert scheduled[0].start_to_close_timeout.seconds == 64 * 120 + 600
            text = str(history)
            assert "private-batch-commit-fixture" not in text and "native-test-design-fixture-key" not in text
            assert (await Replayer(workflows=[NasusTestDesignGenerationWorkflow]).replay_workflow(history)).replay_failure is None
    asyncio.run(verify())
    assert len(attempts) == 2 and len(v["batch_native_sent"]) == 3 and not v["native_calls"]
    result = job(v, ident)
    assert result["status"] == "completed" and result["batch_progress"]["archived_calls"] == 3
    assert read(v, {"generation_id": result["generation_id"]}).json()["result"]["proposal"]["coverage"]["passed_count"] == 0


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
@pytest.mark.parametrize("documents", [3], indirect=True)
def test_real_temporal_cancellation_in_second_batch_retains_first_reply_and_unknown_claim(formal_batches, monkeypatch):
    from temporalio.client import Client, WorkflowFailureError, WorkflowExecutionStatus
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.generation_runtime import TemporalGenerationRuntime, build_generation_activities
    from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
    v = formal_batches
    ident = queued(v, payload=v["batch_request"].model_dump(mode="json"))
    responses = dict(responses_for(v["batch_planned"].input, v["batch_planned"].plan))
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    sent = []
    async def verify():
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def handle(request):
            batch = json.loads(json.loads(request.content)["messages"][-1]["content"])
            sent.append(batch["batch_digest"])
            if len(sent) == 2:
                entered.set()
                try:
                    await asyncio.sleep(120)
                except asyncio.CancelledError:
                    stopped.set()
                    raise
            return httpx.Response(200, json=native_reply("openai_compatible", responses[batch["batch_digest"]]))
        monkeypatch.setattr(v["batch_executor"], "provider", HTTPTestDesignModel(transport=httpx.MockTransport(handle)))
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-batch-cancel-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalGenerationRuntime(config, client)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow],
                activities=build_generation_activities()):
            assert await runtime.start(ident)
            handle_ = client.get_workflow_handle("nasus-test-design-generation:" + ident)
            try:
                await asyncio.wait_for(entered.wait(), 180)
                pending = await asyncio.to_thread(invoke, v, GENERATION_CANCEL_TOOL,
                    {"project_id": v["project_id"], "invocation_id": ident})
                completed(await asyncio.to_thread(confirm, v, pending.json()))
                await runtime.cancel(ident)
                with pytest.raises(WorkflowFailureError):
                    await asyncio.wait_for(handle_.result(), 60)
                assert (await handle_.describe()).status == WorkflowExecutionStatus.CANCELED
                await asyncio.wait_for(stopped.wait(), 15)
            finally:
                await handle_.cancel()
    asyncio.run(verify())
    result = job(v, ident)
    assert result["status"] == "cancelled" and result["generation_id"] is None and result["recovery_request"] is None
    assert result["batch_progress"]["archived_calls"] == result["batch_progress"]["unknown_calls"] == result["batch_progress"]["unstarted_calls"] == 1
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled" and len(sent) == 2 and not v["native_calls"]
