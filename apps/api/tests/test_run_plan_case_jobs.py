"""Real use-case/worker/verifier with explicit journal/transport specimens, not PG or target gold."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.run_plan_case_receipts import RunPlanCaseReceiptAccess
from apps.api.app.application.platform.tool_handlers.run_plan_case_jobs import RunPlanCaseJobToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.application.quality_loop.run_plan_case_jobs import RunPlanCaseJobApplicationService, RunPlanCaseJobTarget
from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from apps.api.app.application.quality_loop.http_fixtures import HttpFixturePhaseRecord, HttpFixtureLifecycleApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL, CASE_CANCEL_TOOL, RunPlanCaseExecutionInvalid
from apps.api.app.domain.quality_loop.run_plan_case_job import CASE_JOB_QUERY_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec
from apps.api.tests.test_run_plan_case_execution import Journal, Runner, Artifacts


@pytest.fixture
def job(case_inputs):
    return case_job(case_inputs)


def case_job(v, runner=None):
    runner, journal, artifacts = runner if runner is not None else Runner(), Journal(), Artifacts()
    worker = RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), journal, artifacts)
    cases = RunPlanCaseApplicationService(v.service, worker)
    actor = UserProfile(id="admin", name="Original administrator", email="case@example.com", role="project_admin")
    state = dict(status="running", deliveries=[], finished=[], cancelled=[], ack=[], before_read=None)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    class Repository:
        def command(self, target):
            assert target.project_id == v.selection.project_id and target.invocation_id == v.snapshot["id"]
            if state["before_read"]: state["before_read"]()
            return dict(selection=v.selection, invocation_id=target.invocation_id, actor_id="admin", status=state["status"],
                command_digest=prepared.scope.command_digest, scope=journal.scope)
        def execution(self, invocation_id, *, require_actor=True):
            return self.command(RunPlanCaseJobTarget(project_id=v.selection.project_id, invocation_id=invocation_id)), actor
        def require_running(self, selection, invocation_id, digest, actor_id):
            assert selection == v.selection and digest == prepared.scope.command_digest and actor_id == "admin"
            if state["status"] != "running": raise RunPlanCaseExecutionInvalid("not running")
        def finish(self, invocation_id, digest, status, *, history=None, require_access=None):
            assert invocation_id == v.snapshot["id"] and digest == prepared.scope.command_digest
            if require_access: require_access()
            if state["status"] != "running": return state["status"]
            state["finished"].append((status, deepcopy(history)))
            state["status"] = v.snapshot["status"] = status
            return status
        def cancel(self, target, *, control_id, actor_id, require_current):
            require_current()
            state["cancelled"].append((target, control_id, actor_id))
            state["status"] = v.snapshot["status"] = "cancelled"
            journal.cancelled = journal.scope is not None
            return "cancelled"
        def cancellation_delivered(self, invocation_id): state["ack"].append(invocation_id)
    class Workflow:
        failure = None
        async def start(self, invocation_id):
            state["deliveries"].append(invocation_id)
            if self.failure: raise self.failure
            return True
        async def cancel(self, invocation_id):
            if self.failure: raise self.failure
    repository, workflow = Repository(), Workflow()
    application = RunPlanCaseJobApplicationService(cases, repository, workflow)
    target = RunPlanCaseJobTarget(project_id=v.selection.project_id, invocation_id=v.snapshot["id"])
    return SimpleNamespace(v=v, runner=runner, journal=journal, application=application, repository=repository,
        workflow=workflow, state=state, target=target, prepared=prepared, actor=actor)


def test_historical_input_read_never_probes_target_renews_consent_or_adopts_reader_identity(case_inputs):
    v = case_inputs
    original = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    read_count = v.state["health_reads"]
    v.snapshot["status"] = "completed"
    v.v.saved["current_use"]["inputs_current"] = v.binding["current_use"]["inputs_current"] = False
    v.state["target_up"] = False
    v.authority.scope(v.selection.project_id).actor_id = "another-current-admin"
    v.authority.scope(v.selection.project_id).fingerprint = acceptance_digest("new reader permissions")
    result = v.service.historical_inputs(original.scope)
    assert result.scope == original.scope and result.plan == original.plan
    assert result.scope.actor_id == "admin" and v.state["health_reads"] == read_count
    assert len(v.runner.commands) == v.state["initial_request_count"]
    with pytest.raises(SourceAccessDenied): v.service.require_current(original)


def test_history_after_unknown_cleanup_retains_original_setup_without_granting_live_execution(case_inputs):
    v = case_inputs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    cleanup = HttpFixtureLifecycleApplicationService._command(v.resolved.scope, "cleanup:session", tuple(v.resolved.manifest["cleanup_groups"]["session"]))
    v.state["phases"] = (v.state["phases"][0], ("cleanup:session", HttpFixturePhaseRecord(cleanup, None)))
    read_count = v.state["health_reads"]
    assert v.service.historical_inputs(prepared.scope).scope == prepared.scope
    assert v.state["health_reads"] == read_count
    with pytest.raises(ValueError): v.service.require_current(prepared)


def test_current_source_revocation_still_denies_original_historical_inputs(case_inputs):
    v = case_inputs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    v.v.state["revoked"] = True
    with pytest.raises(SourceAccessDenied): v.service.historical_inputs(prepared.scope)


def test_dispatch_returns_without_business_execution_and_unknown_rpc_keeps_same_original_job(job):
    v = job
    v.workflow.failure = RuntimeError("unknown transport acknowledgement")
    with pytest.raises(RuntimeError): asyncio.run(v.application.dispatch(v.v.selection, v.target.invocation_id))
    assert not v.runner.commands and v.state["status"] == "running" and not v.state["finished"]
    v.workflow.failure = None
    assert asyncio.run(v.application.deliver(v.target.invocation_id)) == "running"
    assert v.state["deliveries"] == [v.target.invocation_id, v.target.invocation_id]
    assert not v.runner.commands


def test_complete_original_worker_result_is_reread_from_original_archive_before_finalization(job):
    v = job
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    assert len(v.runner.commands) == len(v.journal.outcomes) == 7
    status, receipt = v.state["finished"][0]
    assert status == "completed" and receipt["state"]["case_count"] == receipt["state"]["observed_case_count"] == 7
    assert receipt["state"]["business_coverage_verified"] is False and receipt["state"]["passed_count"] == 0
    v.v.state["target_up"] = False
    before = v.v.state["health_reads"]
    metadata = v.application.metadata(v.target)
    assert metadata["execution_state"] == "observed" and metadata["observed_case_count"] == 7
    assert not {"history", "observations", "scope", "artifact_ref", "cases"} & set(metadata)
    assert v.v.state["health_reads"] == before


def test_unknown_effect_retry_reads_original_claim_instead_of_acquiring_or_resending(job):
    v = job
    v.runner.failure = RuntimeError("lost after dispatch")
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "failed"
    assert len(v.runner.commands) == 1 and len(v.journal.claims) == 1
    v.state["status"] = v.v.snapshot["status"] = "running"
    epoch = v.journal.lease.epoch
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "failed"
    assert len(v.runner.commands) == 1 and v.journal.lease.epoch == epoch
    assert v.state["finished"][-1][1]["state"]["state"] == "outcome_unknown"


def test_native_business_failure_does_not_drop_other_cases_or_turn_into_a_fake_pass(job):
    v = job
    v.runner.failed_case = v.prepared.plan["prepared"]["cases"][0]["case_id"]
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    history = v.application.read(v.target)["history"]
    assert len(history["observations"]) == 7 and history["observations"][0]["status"] == "failed"
    assert history["state"]["passed_count"] == 0


def test_prebind_cancel_is_durable_before_rpc_and_preserves_missing_denominator(job):
    v = job
    v.workflow.failure = RuntimeError("cancel acknowledgement unknown")
    assert asyncio.run(v.application.cancel(v.target, control_id="independent-cancel")) == "cancelled"
    assert v.state["cancelled"] and not v.state["ack"] and not v.runner.commands
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "cancelled"
    metadata = v.application.metadata(v.target)
    assert metadata["execution_state"] == "cancelled" and metadata["case_count"] is None and metadata["bound"] is False


@pytest.mark.parametrize("role", ["viewer", "tester", "qa_lead"])
def test_private_fixture_administrator_policy_is_not_silently_broadened(job, role):
    v = job
    v.v.authority.scope(v.target.project_id).effective_project_role = role
    with pytest.raises(SourceAccessDenied): v.application.read(v.target)
    assert not v.runner.commands


def test_public_receipt_access_reauthorizes_and_broadcast_hides_all_private_input(job):
    v = job
    invocation = ToolInvocation(id=v.target.invocation_id, tool_id=CASE_EXECUTE_TOOL, status="running", summary="private",
        input_payload=deepcopy(v.v.snapshot["input_payload"]))
    access = RunPlanCaseReceiptAccess(v.application)
    access.require_access(invocation)
    public = access.broadcast_view(invocation)
    assert public.input_payload == {} and public.result is None and "private" not in public.summary
    v.v.v.state["revoked"] = True
    with pytest.raises(Exception): access.require_access(invocation)


def test_handler_dispatch_is_deferred_and_metadata_never_contains_private_observations(job):
    v, events = job, []
    async def emit(*args): events.append(args)
    handler = RunPlanCaseJobToolHandler(v.application, SimpleNamespace(emit_tool_status=emit),
        SimpleNamespace(require_invocation_project_scope=lambda _: None))
    invocation = ToolInvocation(id=v.target.invocation_id, tool_id=CASE_EXECUTE_TOOL, status="running", summary="",
        input_payload=deepcopy(v.v.snapshot["input_payload"]))
    asyncio.run(handler.handle(invocation))
    assert not events and not v.runner.commands and v.state["status"] == "running"
    query = ToolInvocation(id="query-original", tool_id=CASE_JOB_QUERY_TOOL, status="running", summary="", input_payload=v.target.model_dump(mode="json"))
    asyncio.run(handler.handle(query))
    assert events[-1][1] == "completed" and events[-1][-1].run_plan_case_job["bound"] is False
    assert "history" not in events[-1][-1].run_plan_case_job


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("fault", [None, "authority", "private", "count_bool", "state", "status", "run", "missing"])
def test_query_receipt_preserves_original_denominator_state_and_no_authority(job, bound, fault):
    v = job
    if bound:
        assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    metadata = v.application.metadata(v.target)
    if fault == "authority": metadata["business_coverage_verified"] = True
    elif fault == "private": metadata["artifact_ref"] = "private/archive"
    elif fault == "count_bool": metadata["observed_case_count"] = True
    elif fault == "state": metadata["execution_state"] = "outcome_unknown" if bound else "observed"
    elif fault == "status": metadata["status"] = "running" if bound else "completed"; metadata["execution_state"] = "cancelled" if bound else "observed"
    elif fault == "run": metadata["run_id"] = "another-original-run"
    elif fault == "missing": metadata.pop("not_dispatched_case_count")
    invocation = ToolInvocation(id="metadata-query", tool_id=CASE_JOB_QUERY_TOOL, status="completed", summary="",
        input_payload=v.target.model_dump(mode="json"), result=ToolResult(invocation_id="metadata-query",
            status="completed", summary="Original metadata only", run_plan_case_job=metadata))
    if fault is None:
        v.application.authorize_receipts((invocation,))
    else:
        with pytest.raises(RunPlanCaseExecutionInvalid):
            v.application.authorize_receipts((invocation,))
