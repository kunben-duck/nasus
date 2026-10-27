"""Canonical multi-batch recovery with actual PG and explicit native HTTP fixtures."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import os
from uuid import uuid4

import pytest

from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GENERATION_CANCEL_TOOL
from apps.api.tests.test_generation_batch_jobs_api import formal_batches
from apps.api.tests.test_generation_batch_results_api import aggregate, ledger, execution, design_scope, publication, documents, evidence_api, read
from apps.api.tests.test_generation_execution_api import queued, job, command
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm


@pytest.fixture
def failed_batches(formal_batches, monkeypatch):
    v = formal_batches
    with monkeypatch.context() as fault:
        def fail(*args, **kwargs):
            raise ValueError("explicit post-reply terminal fixture")
        fault.setattr(v["batch_results"].repository, "record_batch", fail)
        source = queued(v, payload=v["batch_request"].model_dump(mode="json"))
        assert asyncio.run(v["jobs"].run(source)) == "failed"
    state = job(v, source)
    assert state["reply_archived"] and state["generation_id"] is None and not state["provider_outcome_unknown"]
    assert len(state["recovery_request"]["replies"]) == len(v["batch_native_sent"])
    assert "artifact_ref" not in str(state) and "native-test-design-fixture-key" not in str(state)
    v.update(failed_source=source, complete_recovery=state["recovery_request"])
    return v


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_canonical_complete_batch_recovery_owns_new_worker_and_cannot_complete_a_competing_command(failed_batches, monkeypatch):
    v = failed_batches
    first = queued(v, GENERATION_RECOVER_TOOL, v["complete_recovery"])
    second = queued(v, GENERATION_RECOVER_TOOL, v["complete_recovery"])
    v["workflow"].start.assert_awaited_with(second)
    original, attempted = v["jobs"].batch_recovery.repository.record_recovered, []
    def once(*args, **kwargs):
        attempted.append(1)
        if len(attempted) == 1:
            raise RuntimeError("explicit recoverable commit fixture")
        return original(*args, **kwargs)
    monkeypatch.setattr(v["jobs"].batch_recovery.repository, "record_recovered", once)
    with pytest.raises(RuntimeError, match="recoverable commit"):
        asyncio.run(v["jobs"].run(first))
    assert command(v, first).json()["status"] == "running"
    assert asyncio.run(v["jobs"].run(first)) == "completed"
    assert asyncio.run(v["jobs"].run(first)) == "completed"
    state = job(v, first)
    assert state["source_invocation_id"] == v["failed_source"] and state["recovery_request"] is None
    value = read(v, {"generation_id": state["generation_id"]}).json()
    assert value["metadata"]["schema"] == "nasus.test-design-result.v4"
    assert value["metadata"]["recovery_invocation_id"] == first and len(value["metadata"]["call_ids"]) == 3
    assert value["result"]["recovery_request"] == v["complete_recovery"]
    assert value["result"]["proposal"]["coverage"]["passed_count"] == 0
    assert asyncio.run(v["jobs"].run(second)) == "failed"
    assert job(v, second)["generation_id"] is None
    assert command(v, v["failed_source"]).json()["status"] == "failed"
    assert len(v["batch_native_sent"]) == 3 and not v["native_calls"]


def test_public_batch_recovery_rejects_changed_pins_and_cancellation_without_egress(failed_batches):
    v = failed_batches
    for mutation in ("partial", "response", "reservation", "schema", "private"):
        value = deepcopy(v["complete_recovery"])
        if mutation == "partial": value["replies"] = []
        if mutation == "response": value["replies"][0]["response_hash"] = value["request_hash"]
        if mutation == "reservation": value["reservation_hash"] = value["request_hash"]
        if mutation == "schema": value["schema_version"] = "nasus.test-design-batch-recovery.unknown"
        if mutation == "private": value["replies"][0]["artifact_ref"] = "s3://forbidden/private"
        pending = invoke(v, GENERATION_RECOVER_TOOL, value, key=uuid4().hex).json()
        assert pending["status"] == "waiting_confirmation"
        response = confirm(v, pending)
        assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    recovery = queued(v, GENERATION_RECOVER_TOOL, v["complete_recovery"])
    pending = invoke(v, GENERATION_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": recovery}).json()
    completed(confirm(v, pending))
    assert asyncio.run(v["jobs"].run(recovery)) == "cancelled"
    assert job(v, recovery)["generation_id"] is None and job(v, recovery)["recovery_request"] is None
    assert command(v, v["failed_source"]).json()["status"] == "failed"
    assert len(v["batch_native_sent"]) == 1 and not v["native_calls"]


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
@pytest.mark.parametrize("documents", [3], indirect=True)
def test_real_temporal_complete_batch_recovery_retries_only_the_commit_and_replays_history(failed_batches, monkeypatch):
    from temporalio.client import Client
    from temporalio.worker import Replayer, Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.generation_runtime import TemporalGenerationRuntime, build_generation_activities
    from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
    v = failed_batches
    ident = queued(v, GENERATION_RECOVER_TOOL, v["complete_recovery"])
    original, attempts = v["jobs"].batch_recovery.repository.record_recovered, []
    def fail_once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("private-recovery-fixture-must-not-enter-history")
        return original(*args, **kwargs)
    monkeypatch.setattr(v["jobs"].batch_recovery.repository, "record_recovered", fail_once)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-batch-recovery-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalGenerationRuntime(config, client)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow],
                activities=build_generation_activities()):
            assert await runtime.start(ident)
            handle = client.get_workflow_handle("nasus-test-design-generation:" + ident)
            assert await asyncio.wait_for(handle.result(), 300) == "completed"
            assert not await runtime.start(ident)
            history = await handle.fetch_history()
            assert "private-recovery-fixture" not in str(history) and "native-test-design-fixture-key" not in str(history)
            assert (await Replayer(workflows=[NasusTestDesignGenerationWorkflow]).replay_workflow(history)).replay_failure is None
    asyncio.run(verify())
    assert len(attempts) == 2 and len(v["batch_native_sent"]) == 3 and not v["native_calls"]
    assert job(v, ident)["status"] == "completed"
    assert command(v, v["failed_source"]).json()["status"] == "failed"
