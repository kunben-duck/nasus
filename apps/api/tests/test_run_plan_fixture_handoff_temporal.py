"""Actual Temporal v3 workflow; source/setup/journal/target are explicit specimens."""
import asyncio
import os
import time
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio.client import Client, WorkflowFailureError
from temporalio.worker import Replayer, Worker

from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.workflow.nasus_run_plan_case_workflow import NasusRunPlanCaseWorkflow
from apps.api.app.infrastructure.workflow.run_plan_case_runtime import TemporalRunPlanCaseRuntime, build_run_plan_case_activities
from apps.api.tests.test_run_plan_case_jobs import case_job
from apps.api.tests.test_run_plan_fixture_handoff import NativeRunner, fixture_inputs, spec


@pytest.fixture
def temporal_fixture_job(fixture_inputs):
    fixture_inputs.snapshot["id"] = "fixture-temporal-test-" + uuid4().hex
    return case_job(fixture_inputs, NativeRunner())


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires an explicitly enabled Temporal server")
def test_real_temporal_retry_after_v3_native_archive_reads_original_output_without_new_claim(temporal_fixture_job, monkeypatch):
    import apps.api.app.bootstrap as bootstrap
    v = temporal_fixture_job
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(run_plan_case_jobs=v.application))
    original_finish, faults = v.repository.finish, []

    def finish(invocation_id, digest, status, **kwargs):
        if not faults:
            assert kwargs["history"]["state"]["schema"] == "nasus.run-plan-case-state.v2"
            faults.append(invocation_id)
            raise RuntimeError("explicit original terminal acknowledgement lost after full native archive")
        return original_finish(invocation_id, digest, status, **kwargs)

    monkeypatch.setattr(v.repository, "finish", finish)

    async def verify():
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"], task_queue="nasus-test-fixture-handoff-" + uuid4().hex)
        client = await asyncio.wait_for(Client.connect(config.address, namespace=config.namespace), 10)
        runtime = TemporalRunPlanCaseRuntime(config=config, client=client)
        v.application.workflow = runtime
        handle = None
        try:
            async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusRunPlanCaseWorkflow], activities=build_run_plan_case_activities()):
                with actor_scope(v.actor):
                    assert await v.application.dispatch(v.v.selection, v.target.invocation_id) == "running"
                handle = client.get_workflow_handle("nasus-run-plan-cases:" + v.target.invocation_id)
                assert await asyncio.wait_for(handle.result(), 150) == "completed"
                assert faults == [v.target.invocation_id] and len(v.state["finished"]) == 1
                assert len(v.runner.commands) == len(v.journal.claims) == len(v.journal.outcomes) == len(v.v.selection.fixture_setups)
                history = v.application.read(v.target)["history"]
                assert history == v.state["finished"][0][1] and all(item["status"] == "failed" for item in history["observations"])
                assert history["state"]["passed_count"] == history["state"]["executed_on_target_count"] == 0
                assert await runtime.start(v.target.invocation_id) is False
                await Replayer(workflows=[NasusRunPlanCaseWorkflow]).replay_workflow(await handle.fetch_history())
        finally:
            if handle is not None:
                await runtime.cancel(v.target.invocation_id)

    asyncio.run(verify())


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires an explicitly enabled Temporal server")
def test_real_temporal_cancel_during_v3_input_preparation_joins_guard_without_resource_or_claim(temporal_fixture_job, monkeypatch):
    import apps.api.app.bootstrap as bootstrap
    v, entered = temporal_fixture_job, Event()
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(run_plan_case_jobs=v.application))
    original_prepare = v.v.service.prepare

    def wait_for_stop(*args, require_work, **kwargs):
        entered.set()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            require_work()
            time.sleep(.01)
        raise TimeoutError("original preparation cancellation was not delivered")

    monkeypatch.setattr(v.v.service, "prepare", wait_for_stop)

    async def verify():
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"], task_queue="nasus-test-fixture-cancel-" + uuid4().hex)
        client = await asyncio.wait_for(Client.connect(config.address, namespace=config.namespace), 10)
        runtime = TemporalRunPlanCaseRuntime(config=config, client=client)
        v.application.workflow = runtime
        handle = None
        try:
            async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusRunPlanCaseWorkflow], activities=build_run_plan_case_activities()):
                with actor_scope(v.actor):
                    assert await v.application.dispatch(v.v.selection, v.target.invocation_id) == "running"
                handle = client.get_workflow_handle("nasus-run-plan-cases:" + v.target.invocation_id)
                assert await asyncio.to_thread(entered.wait, 20), "original preparation Activity was not started"
                with actor_scope(v.actor):
                    assert await v.application.cancel(v.target, control_id="independent-temporal-cancel") == "cancelled"
                with pytest.raises(WorkflowFailureError):
                    await asyncio.wait_for(handle.result(), 30)
                assert not v.runner.commands and not v.journal.claims and v.journal.scope is None
                assert v.state["ack"] == [v.target.invocation_id] and not v.state["finished"]
                assert await runtime.start(v.target.invocation_id) is False
                assert await v.application.run(v.target.invocation_id) == "cancelled"
                await Replayer(workflows=[NasusRunPlanCaseWorkflow]).replay_workflow(await handle.fetch_history())
        finally:
            monkeypatch.setattr(v.v.service, "prepare", original_prepare)
            if handle is not None:
                await runtime.cancel(v.target.invocation_id)

    asyncio.run(verify())
