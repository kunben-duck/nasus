"""Actual Temporal adapter with explicit transport doubles, never a Temporal server."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError, ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from apps.api.app.infrastructure.workflow.run_plan_case_runtime import TemporalRunPlanCaseRuntime, build_run_plan_case_activities, reconcile_run_plan_cases_once
from apps.api.app.infrastructure.workflow.nasus_run_plan_case_workflow import NasusRunPlanCaseWorkflow


@pytest.mark.parametrize("prior", [None, *tuple(WorkflowExecutionStatus)])
def test_same_identity_delivery_never_reopens_a_terminal_workflow(monkeypatch, prior):
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    calls = []
    async def start(function, value, **options):
        calls.append((function, value, options))
        if prior is not None: raise WorkflowAlreadyStartedError(options["id"], "NasusRunPlanCaseWorkflow", run_id="original-run")
    async def describe(**options):
        assert options == {"rpc_timeout": timedelta(seconds=10)}
        return SimpleNamespace(status=prior)
    def handle(ident):
        assert ident == "nasus-run-plan-cases:original-command"
        return SimpleNamespace(describe=describe)
    runtime = TemporalRunPlanCaseRuntime(config=SimpleNamespace(task_queue="nasus-worker"),
        client=SimpleNamespace(start_workflow=start, get_workflow_handle=handle))
    assert asyncio.run(runtime.start("original-command")) is (prior is None or prior == WorkflowExecutionStatus.RUNNING)
    assert calls == [(NasusRunPlanCaseWorkflow.run, "original-command", dict(id="nasus-run-plan-cases:original-command",
        task_queue="nasus-worker-run-plan-cases", id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, rpc_timeout=timedelta(seconds=10)))]


@pytest.mark.parametrize("status", [None, RPCStatusCode.NOT_FOUND, RPCStatusCode.UNAVAILABLE, RPCStatusCode.PERMISSION_DENIED])
def test_cancel_acknowledges_only_success_or_absent_original_workflow(monkeypatch, status):
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    calls = []
    async def cancel(**options):
        calls.append(options)
        if status: raise RPCError("private transport error", status, b"")
    runtime = TemporalRunPlanCaseRuntime(config=SimpleNamespace(task_queue="worker"), client=SimpleNamespace(
        get_workflow_handle=lambda ident: SimpleNamespace(cancel=cancel) if ident == "nasus-run-plan-cases:original" else None))
    if status in {None, RPCStatusCode.NOT_FOUND}: asyncio.run(runtime.cancel("original"))
    else:
        with pytest.raises(RPCError): asyncio.run(runtime.cancel("original"))
    assert calls == [{"rpc_timeout": timedelta(seconds=10)}]


def test_reconciler_delivers_cancellation_first_pages_original_ids_and_does_not_lose_other_commands():
    calls = []
    def cancellations(*, after_id): return ("cancel-a", "cancel-b") if after_id is None else ()
    def pending(*, after_id): return ("run-a", "run-b") if after_id is None else ("run-c",) if after_id == "run-b" else ()
    def ack(ident): calls.append(("ack", ident))
    async def cancel(ident): calls.append(("cancel", ident))
    async def deliver(ident):
        calls.append(("deliver", ident))
        if ident == "run-a": raise RuntimeError("unknown delivery")
    repository = SimpleNamespace(pending_cancellations=cancellations, pending=pending, cancellation_delivered=ack)
    asyncio.run(reconcile_run_plan_cases_once(SimpleNamespace(cancel=cancel), repository, jobs=SimpleNamespace(deliver=deliver)))
    assert calls == [("cancel", "cancel-a"), ("ack", "cancel-a"), ("cancel", "cancel-b"), ("ack", "cancel-b"),
        ("deliver", "run-a"), ("deliver", "run-b"), ("deliver", "run-c")]


@pytest.mark.parametrize("failure", [False, True])
def test_activity_uses_container_heartbeat_and_redacts_infrastructure_fault(monkeypatch, failure):
    from temporalio import activity
    import apps.api.app.bootstrap as bootstrap
    beats = []
    monkeypatch.setattr(activity, "heartbeat", lambda value: beats.append(value))
    async def run(ident):
        await asyncio.sleep(0.01)
        if failure: raise RuntimeError("private archive credentials")
        return "completed"
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(run_plan_case_jobs=SimpleNamespace(run=run)))
    invoke = build_run_plan_case_activities()[0]
    if failure:
        with pytest.raises(ApplicationError) as raised: asyncio.run(invoke("original-command"))
        assert "private" not in str(raised.value) and raised.value.type == "RunPlanCaseInfrastructureFailure"
    else: assert asyncio.run(invoke("original-command")) == "completed"
    assert beats == [{"invocation_id": "original-command"}]
