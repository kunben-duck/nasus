"""Real Temporal retry policy; application/ledger specimens, not PG or target gold."""
import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.workflow.http_fixture_runtime import TemporalHttpFixtureRuntime, build_http_fixture_activities
from apps.api.app.infrastructure.workflow.nasus_http_fixture_workflow import NasusHttpFixtureWorkflow
from apps.api.app.infrastructure.workflow.run_plan_case_runtime import TemporalRunPlanCaseRuntime, build_run_plan_case_activities
from apps.api.app.infrastructure.workflow.nasus_run_plan_case_workflow import NasusRunPlanCaseWorkflow


WORKFLOWS = (
    (TemporalHttpFixtureRuntime, NasusHttpFixtureWorkflow, build_http_fixture_activities,
        "http_fixture_jobs", "nasus-http-fixture:", "HttpFixture"),
    (TemporalRunPlanCaseRuntime, NasusRunPlanCaseWorkflow, build_run_plan_case_activities,
        "run_plan_case_jobs", "nasus-run-plan-cases:", "RunPlanCase"),
)


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires an explicitly enabled Temporal server")
@pytest.mark.parametrize("runtime_type,workflow,factory,service,workflow_prefix,error_prefix", WORKFLOWS)
@pytest.mark.parametrize("failure", (
    PermissionError("private expired original consent"),
    StaleSourceAccessScope("private original source revoked"),
    PlatformApplicationError("source_access_denied", "private source forbidden", 403),
))
def test_real_temporal_denial_ends_original_activity_without_retry_or_permission_renewal(
        monkeypatch, runtime_type, workflow, factory, service, workflow_prefix, error_prefix, failure):
    import apps.api.app.bootstrap as bootstrap
    command_id = "authority-policy-" + uuid4().hex
    calls = []

    async def run(ident):
        assert ident == command_id
        calls.append("run")
        raise failure

    async def finish(ident):
        assert ident == command_id and calls == ["run"]
        calls.append("finish")
        return "failed"

    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(**{
        service: SimpleNamespace(run=run, fail=finish)}))

    async def verify():
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-test-authority-policy-" + uuid4().hex)
        client = await asyncio.wait_for(Client.connect(config.address, namespace=config.namespace), 10)
        runtime = runtime_type(config=config, client=client)
        handle = None
        try:
            async with Worker(client, task_queue=runtime.task_queue, workflows=[workflow], activities=factory()):
                assert await runtime.start(command_id) is True
                handle = client.get_workflow_handle(workflow_prefix + command_id)
                assert await asyncio.wait_for(handle.result(), 30) == "failed"
                assert calls == ["run", "finish"]
                history = await handle.fetch_history()
                failures = [event.activity_task_failed_event_attributes.failure for event in history.events
                    if event.HasField("activity_task_failed_event_attributes")]
                assert len(failures) == 1
                info = failures[0].application_failure_info
                assert info.type == error_prefix + "AuthorityDenied" and info.non_retryable is True
                assert "private" not in failures[0].message
                assert await runtime.start(command_id) is False
                assert calls == ["run", "finish"]
                await Replayer(workflows=[workflow]).replay_workflow(history)
        finally:
            if handle is not None:
                await runtime.cancel(command_id)

    asyncio.run(verify())
