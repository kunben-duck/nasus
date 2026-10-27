"""Real orchestration with transport/port doubles, not a live Temporal server."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobTarget, HttpFixtureJobApplicationService
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkBusy
from apps.api.app.infrastructure.workflow.http_fixture_runtime import (
    TemporalHttpFixtureRuntime, build_http_fixture_activities, reconcile_http_fixtures_once,
)
from apps.api.app.infrastructure.workflow.nasus_http_fixture_workflow import NasusHttpFixtureWorkflow


@pytest.mark.parametrize("prior_status", [None, WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.COMPLETED,
    WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.CANCELED, WorkflowExecutionStatus.TERMINATED,
    WorkflowExecutionStatus.TIMED_OUT])
def test_runtime_reuses_only_original_workflow_id_and_never_reopens_terminal_execution(monkeypatch, prior_status):
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    calls = []
    async def start(function, value, **options):
        calls.append((function, value, options))
        if prior_status is not None:
            raise WorkflowAlreadyStartedError(options["id"], "NasusHttpFixtureWorkflow", run_id="original-run")
    async def describe(**options):
        calls.append(("describe", options))
        return SimpleNamespace(status=prior_status)
    def handle(ident):
        assert ident == "nasus-http-fixture:original-command"
        return SimpleNamespace(describe=describe)
    runtime = TemporalHttpFixtureRuntime(config=SimpleNamespace(task_queue="nasus-worker"),
        client=SimpleNamespace(start_workflow=start, get_workflow_handle=handle))
    assert asyncio.run(runtime.start("original-command")) is (prior_status is None or prior_status == WorkflowExecutionStatus.RUNNING)
    function, value, options = calls[0]
    assert function is NasusHttpFixtureWorkflow.run and value == "original-command"
    assert options == {"id": "nasus-http-fixture:original-command", "task_queue": "nasus-worker-http-fixture",
        "id_reuse_policy": WorkflowIDReusePolicy.REJECT_DUPLICATE, "rpc_timeout": timedelta(seconds=10)}
    assert len(calls) == (1 if prior_status is None else 2)


@pytest.mark.parametrize("status", [None, RPCStatusCode.NOT_FOUND, RPCStatusCode.UNAVAILABLE, RPCStatusCode.PERMISSION_DENIED])
def test_cancellation_acknowledges_only_success_or_missing_original_workflow(monkeypatch, status):
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    calls = []
    async def cancel(**options):
        calls.append(options)
        if status is not None:
            raise RPCError("private cancellation transport failure", status, b"")
    def handle(ident):
        assert ident == "nasus-http-fixture:original-command"
        return SimpleNamespace(cancel=cancel)
    runtime = TemporalHttpFixtureRuntime(config=SimpleNamespace(task_queue="nasus-worker"),
        client=SimpleNamespace(get_workflow_handle=handle))
    if status in {None, RPCStatusCode.NOT_FOUND}:
        asyncio.run(runtime.cancel("original-command"))
    else:
        with pytest.raises(RPCError): asyncio.run(runtime.cancel("original-command"))
    assert calls == [{"rpc_timeout": timedelta(seconds=10)}]


def test_reconciliation_paginates_cancellations_first_and_does_not_starve_after_unknown_ack(caplog):
    identifiers = ["fixture-%03d" % index for index in range(105)]
    calls, delivered, ended = [], [], []
    def page(*, after_id=None):
        return [(ident, "project") for ident in identifiers if after_id is None or ident > after_id][:100]
    async def cancel(ident):
        calls.append(("cancel", ident))
        if ident == identifiers[0]: raise RuntimeError("private unknown cancellation acknowledgement")
    async def start(ident):
        calls.append(("start", ident))
        if ident == identifiers[1]: raise RuntimeError("private unknown start acknowledgement")
        return ident != identifiers[-1]
    repository = SimpleNamespace(pending=page, pending_cancellations=page,
        cancellation_delivered=lambda target: delivered.append(target),
        delivery=lambda ident: {"status": "running", "bound": True, "authority": "authority:" + ident},
        failure_command=lambda ident: ("running", "authority:" + ident),
        finish=lambda authority, status: ended.append((authority, status)))
    workflow = SimpleNamespace(start=start, cancel=cancel)
    jobs = HttpFixtureJobApplicationService(SimpleNamespace(grants=None), repository, workflow)
    asyncio.run(reconcile_http_fixtures_once(workflow, repository, jobs=jobs))
    assert calls == [("cancel", ident) for ident in identifiers] + [("start", ident) for ident in identifiers]
    assert delivered == [HttpFixtureJobTarget(project_id="project", invocation_id=ident) for ident in identifiers[1:]]
    assert ended == [("authority:" + identifiers[-1], "failed")]
    assert "private unknown" not in caplog.text


def test_terminal_workflow_failure_delivery_waits_for_original_lease_without_new_workflow(caplog):
    calls = []
    async def start(ident): calls.append(("start", ident)); return False
    def finish(authority, status):
        calls.append(("finish", authority, status))
        raise HttpFixtureWorkBusy("private original lease still live")
    repository = SimpleNamespace(pending_cancellations=lambda **_: [],
        pending=lambda **options: [("original-command", "project")] if options["after_id"] is None else [],
        delivery=lambda _: {"status": "running", "bound": True, "authority": "original-authority"},
        failure_command=lambda _: ("running", "original-authority"), finish=finish)
    workflow = SimpleNamespace(start=start)
    jobs = HttpFixtureJobApplicationService(SimpleNamespace(grants=None), repository, workflow)
    asyncio.run(reconcile_http_fixtures_once(workflow, repository, jobs=jobs))
    assert calls == [("start", "original-command"), ("finish", "original-authority", "failed")]
    assert "delivery deferred" in caplog.text and "private original" not in caplog.text


@pytest.mark.parametrize("ending", ["success", "failure", "cancelled"])
def test_activity_preserves_cancellation_and_sanitizes_failure_while_joining_heartbeat(monkeypatch, ending):
    from apps.api.app import bootstrap
    from temporalio import activity

    heartbeats = []
    monkeypatch.setattr(activity, "heartbeat", lambda value: heartbeats.append(value))
    async def run(ident):
        assert ident == "original-command"
        await asyncio.sleep(0)
        if ending == "failure": raise RuntimeError("private provider and resource details")
        if ending == "cancelled": raise asyncio.CancelledError()
        return "completed"
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(http_fixture_jobs=SimpleNamespace(run=run)))
    invoke = build_http_fixture_activities()[0]
    async def exercise():
        if ending == "success": assert await invoke("original-command") == "completed"
        elif ending == "failure":
            with pytest.raises(ApplicationError) as error: await invoke("original-command")
            assert error.value.type == "HttpFixtureInfrastructureFailure" and "private" not in str(error.value)
            assert error.value.__suppress_context__ is True
        else:
            with pytest.raises(asyncio.CancelledError): await invoke("original-command")
        assert heartbeats == [{"invocation_id": "original-command"}]
        assert not any(task is not asyncio.current_task() and not task.done() for task in asyncio.all_tasks())
    asyncio.run(exercise())
