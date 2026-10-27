"""Lifecycle and session specimens, not real Temporal, PostgreSQL or exweb execution."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import current_user
from apps.api.app.application.platform.http_fixture_job_receipts import HttpFixtureJobReceiptAccess
from apps.api.app.application.platform.tool_handlers.http_fixture_jobs import HttpFixtureJobToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService, HttpFixtureJobTarget
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureOutcomeUnknown
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FIXTURE_QUERY_TOOL
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence import http_fixture_job_repository as adapter
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord as Intent, HttpFixtureDispatchCommandRecord as Binding
from apps.api.app.infrastructure.persistence.http_fixture_job_models import HttpFixtureCancellationRecord as Cancellation, HttpFixtureCancellationDeliveryRecord as Delivery
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureWorkLeaseRecord as Lease
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch, HttpFixtureResultRecord as Result
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal as Journal
from apps.api.app.application.quality_loop.http_fixtures import HttpFixturePhaseRecord, HttpFixtureLifecycleApplicationService
from apps.api.app.infrastructure.runner.request_wire import runner_request_hash
from apps.api.tests.test_http_fixtures import Runner
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkBusy
from apps.api.tests.test_http_fixture_commands import command_specimen
from apps.api.tests.test_http_fixture_execution import selection
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


@pytest.fixture
def job_specimen(command_specimen, monkeypatch):
    v = command_specimen
    v.command.revision, v.command.conversation_id, v.command.summary = 0, "original-conversation", ""
    old_add = v.session.add
    def add(row):
        old_add(row)
        if isinstance(row, (Cancellation, Delivery)):
            v.rows[(type(row), row.invocation_id)] = row
    v.session.add = add
    @contextmanager
    def scope(): yield v.session
    monkeypatch.setattr(adapter, "session_scope", scope)
    v.target = HttpFixtureJobTarget(project_id=v.inputs.selection.project_id, invocation_id=v.command.id)
    v.control = ToolInvocationRecord(id="independent-cancellation", tool_id=FIXTURE_CANCEL_TOOL, status="running", conversation_id="control-conversation",
        input_payload={**v.target.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_at": v.session.now.isoformat(),
            "confirmed_actor_id": "other-administrator"})
    v.rows[(ToolInvocationRecord, v.control.id)] = v.control
    v.job_repository = adapter.HttpFixtureJobRepository()
    v.outbox = []
    monkeypatch.setattr(adapter.EventOutboxRepository, "append", lambda self, event, **kwargs: v.outbox.append(event))
    return v


def test_cancellation_locks_original_command_and_appends_delivery_without_renewing_or_reopening(job_specimen):
    v = job_specimen
    original_input = deepcopy(v.command.input_payload)
    assert v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None) == "cancelled"
    assert v.command.id in v.session.locks and v.control.id in v.session.locks
    assert len(v.outbox) == 2 and v.command.input_payload == original_input
    row = v.rows[(Cancellation, v.command.id)]
    old = deepcopy(row.payload)
    v.session.now += timedelta(days=2)
    assert v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None) == "cancelled"
    assert row.payload == old and len(v.outbox) == 2
    v.job_repository.cancellation_delivered(v.target)
    v.job_repository.cancellation_delivered(v.target)
    assert len(v.outbox) == 3 and v.rows[(Delivery, v.command.id)].cancellation_digest == acceptance_digest(old)
    assert v.job_repository.finish(v.authority, "failed") == "cancelled"
    assert v.command.status == "cancelled" and len(v.outbox) == 3
    audits = [row for row in v.session.added if type(row).__name__ == "AuditEventRecord"]
    assert audits[0].actor == "other-administrator" and audits[0].event_metadata == {"control_id": v.control.id}
    assert audits[-1].actor_kind == "system"
    for event in v.outbox[1:]: v.job_repository.verify_event(v.session, event)


@pytest.mark.parametrize("change", ["target", "tool", "actor", "confirmation", "expired", "future", "naive", "extra"])
def test_cancellation_rejects_changed_or_unconfirmed_control_without_terminal_write(job_specimen, change):
    v = job_specimen
    if change == "target": v.control.input_payload["invocation_id"] = "other-command"
    elif change == "tool": v.control.tool_id = FIXTURE_COMMAND_TOOL
    elif change == "actor": v.control.input_payload["confirmed_actor_id"] = "another"
    elif change == "confirmation": v.control.input_payload["confirmed_by_user"] = 1
    elif change == "expired": v.session.now += timedelta(seconds=901)
    elif change == "future": v.session.now -= timedelta(seconds=1)
    elif change == "naive": v.control.input_payload["confirmed_at"] = v.session.now.replace(tzinfo=None).isoformat()
    else: v.control.input_payload["execution_authorized"] = True
    with pytest.raises((HttpFixtureInvalid, ValueError)):
        v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    assert v.command.status == "running" and not v.outbox and (Cancellation, v.command.id) not in v.rows


@pytest.mark.parametrize("change", ["original_input", "control_input", "time", "project", "digest", "authority", "delivery"])
def test_cancellation_replay_rejects_even_rehashed_ancestry_or_false_authority_changes(job_specimen, change):
    v = job_specimen
    v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    row = v.rows[(Cancellation, v.command.id)]
    if change == "original_input": v.command.input_payload["idempotency_key"] = "changed"
    elif change == "control_input": v.control.input_payload["idempotency_key"] = "changed"
    elif change == "delivery":
        v.job_repository.cancellation_delivered(v.target)
        row = v.rows[(Delivery, v.command.id)]
        row.payload["cancellation_digest"] = acceptance_digest("other")
        row.cancellation_digest = row.payload["cancellation_digest"]
    else:
        key, value = {"time": ("recorded_at", (v.session.now - timedelta(days=1)).isoformat()),
            "project": ("project_id", "another"), "digest": ("request_digest", acceptance_digest("another")),
            "authority": ("business_coverage_verified", True)}[change]
        row.payload[key] = value
        if key in row.__table__.columns: setattr(row, key, value)
    row.content_hash = acceptance_digest(row.payload)
    with pytest.raises((HttpFixtureInvalid, ValueError)):
        v.job_repository._cancellation(v.session, v.command.id)


def test_failure_waits_for_live_worker_and_does_not_invent_completion(job_specimen):
    v = job_specimen
    v.rows[(Lease, v.value["work_id"])] = SimpleNamespace(expires_at=v.session.now + timedelta(seconds=10))
    with pytest.raises(HttpFixtureWorkBusy): v.job_repository.finish(v.authority, "failed")
    assert v.command.status == "running" and not v.outbox
    with pytest.raises(HttpFixtureInvalid): v.job_repository.finish(v.authority, "completed")
    with pytest.raises(HttpFixtureInvalid): v.job_repository.finish(v.authority, "cancelled")
    v.session.now += timedelta(seconds=11)
    assert v.job_repository.finish(v.authority, "failed") == "failed"
    assert len(v.outbox) == 1 and v.command.result_payload["http_fixture_job"] is None
    assert v.job_repository.finish(v.authority, "failed") == "failed" and len(v.outbox) == 1


def test_failed_preparation_can_end_without_fabricating_an_intent(job_specimen):
    v = job_specimen
    v.rows.pop((Intent, v.command.id))
    assert v.job_repository.finish(v.authority, "failed") == "failed"
    assert (Intent, v.command.id) not in v.rows and len(v.outbox) == 1


@pytest.mark.parametrize("confirmed_at", [None, 1, "not-a-timestamp"])
def test_invalid_cancellation_clock_is_a_typed_rejection_without_a_terminal_write(job_specimen, confirmed_at):
    v = job_specimen
    v.control.input_payload["confirmed_at"] = confirmed_at
    with pytest.raises(HttpFixtureInvalid):
        v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    assert v.command.status == "running" and not v.outbox and (Cancellation, v.command.id) not in v.rows


def test_missing_cancellation_clock_does_not_fabricate_confirmation(job_specimen):
    v = job_specimen
    v.control.input_payload.pop("confirmed_at")
    with pytest.raises(HttpFixtureInvalid):
        v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    assert v.command.status == "running" and not v.outbox


def test_original_job_state_cannot_hide_a_lost_dispatch_under_not_dispatched(job_specimen, monkeypatch):
    v = job_specimen
    observed_phase(v, monkeypatch)
    ident = Journal._identity(v.inputs.scope, "setup")
    v.rows.pop((Dispatch, ident))
    v.rows.pop((Result, ident))
    assert (Binding, ident) in v.rows
    with pytest.raises(HttpFixtureInvalid):
        v.job_repository.state(v.inputs, v.authority, (("setup", None),))
    assert v.command.status == "running" and not v.outbox and (Dispatch, ident) not in v.rows


def observed_phase(v, monkeypatch, *, unknown=False):
    from dataclasses import asdict
    from apps.api.app.infrastructure.persistence import http_fixture_command_repository as commands

    scope = v.inputs.scope
    command = HttpFixtureLifecycleApplicationService._command(scope, "setup", tuple(v.inputs.manifest["setup_steps"]))
    phase_id = Journal._identity(scope, "setup")
    fields = {"claim_id": phase_id, "project_id": scope.project_id, "attempt_id": scope.attempt_id, "case_id": scope.case_id,
        "phase": "setup", **v.inputs.parent.model_dump(mode="json"), "image_revision_id": "protocol-image", "manifest_id": "protocol-manifest",
        "scope_digest": scope.digest, "command_digest": acceptance_digest(asdict(command)), "request_hash": runner_request_hash(command),
        "actor_id": v.inputs.consent.actor_id, "recorded_at": v.value["recorded_at"], "status": "reserved"}
    payload = {**fields, "schema": "nasus.http-fixture-dispatch.v4", "scope": asdict(scope), "command": Journal._command_value(command),
        "canonical_command": {**v.authority.model_dump(mode="json"), "intent_digest": acceptance_digest(v.value)},
        "operation_consent": v.inputs.consent.pin,
        "work_ownership": {"work_id": v.value["work_id"], "owner_id": "original-worker", "epoch": 1},
        **{key: False for key in commands.FALSE_AUTHORITIES}}
    v.rows[(Dispatch, phase_id)] = Journal._row(Dispatch, payload)
    # Full worker/consent parent validation is covered by actual adapter/PG tests;
    # this specimen exercises the new original-command state and result checks.
    monkeypatch.setattr(commands, "verify_dispatch_ownership", lambda *_: {"owner_id": "original-worker"})
    monkeypatch.setattr(commands, "verify_dispatch_consent", lambda *_: v.inputs.consent.pin)
    v.repository.fence(v.inputs, v.authority).claim(v.session, payload)
    if unknown:
        return (("setup", HttpFixturePhaseRecord(command, None)),)
    execution = Runner().execute_owned_http(command, environment_id=scope.environment_id, artifact_hash=scope.artifact_hash,
        inventory_hash=scope.inventory_hash, require_work=lambda: None)
    receipt = adapter.OwnedHttpFixtureObservationVerifier().verify(command, execution,
        environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
    result = {"schema": "nasus.http-fixture-result.v1", "claim_id": phase_id, "project_id": scope.project_id,
        "actor_id": v.inputs.consent.actor_id, "recorded_at": v.value["recorded_at"], "status": execution.result.status,
        "dispatch_digest": acceptance_digest(payload), "receipt_digest": acceptance_digest(receipt),
        "artifact_ref": "s3://private-protocol-specimen/archived", "artifact_hash": acceptance_digest("archive"),
        **{key: False for key in commands.FALSE_AUTHORITIES}}
    v.rows[(Result, phase_id)] = Journal._row(Result, result)
    return (("setup", HttpFixturePhaseRecord(command, execution)),)


@pytest.mark.parametrize("stage", ["not_dispatched", "outcome_unknown", "observed"])
def test_original_observation_states_cannot_upgrade_unknown_or_business_coverage(job_specimen, monkeypatch, stage):
    v = job_specimen
    history = (("setup", None),) if stage == "not_dispatched" else observed_phase(v, monkeypatch, unknown=stage == "outcome_unknown")
    state = v.job_repository.state(v.inputs, v.authority, history)
    assert state["phases"][0]["state"] == stage
    assert all(state[key] is False for key in adapter.FALSE_AUTHORITIES)
    assert "artifact_ref" not in str(state) and "session_original" not in str(state)
    if stage == "observed":
        assert v.job_repository.finish(v.authority, "completed", inputs=v.inputs, history=history, require_current=lambda: None) == "completed"
        assert v.command.result_payload["http_fixture_job"] is None
    else:
        with pytest.raises(HttpFixtureInvalid):
            v.job_repository.finish(v.authority, "completed", inputs=v.inputs, history=history, require_current=lambda: None)
        assert v.command.status == "running" and not v.outbox


@pytest.mark.parametrize("change", ["missing_archive", "result_digest", "command", "duplicate_phase", "omitted_phase"])
def test_original_job_state_rejects_changed_or_incomplete_evidence(job_specimen, monkeypatch, change):
    v = job_specimen
    history = observed_phase(v, monkeypatch)
    if change == "missing_archive": history = (("setup", HttpFixturePhaseRecord(history[0][1].command, None)),)
    elif change == "result_digest":
        result = next(row for (model, _), row in v.rows.items() if model is Result)
        result.payload["receipt_digest"] = result.receipt_digest = acceptance_digest("other")
        result.content_hash = acceptance_digest(result.payload)
    elif change == "command":
        from dataclasses import replace
        history = (("setup", HttpFixturePhaseRecord(replace(history[0][1].command, timeout_ms=120000), history[0][1].execution)),)
    elif change == "duplicate_phase": history += history
    else: history = ()
    with pytest.raises(HttpFixtureInvalid): v.job_repository.state(v.inputs, v.authority, history)
    assert v.command.status == "running" and not v.outbox


def test_cancel_event_tamper_and_missing_request_fail_without_repair(job_specimen):
    v = job_specimen
    v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    event = v.outbox[-1]
    for changed in (event.model_copy(update={"patch": {**event.patch, "passed_count": 1}}),
            event.model_copy(update={"conversation_id": "other"}), event.model_copy(update={"occurred_at": "changed"})):
        with pytest.raises(HttpFixtureInvalid): v.job_repository.verify_event(v.session, changed)
    v.rows.pop((Cancellation, v.command.id))
    with pytest.raises(HttpFixtureInvalid): v.job_repository.verify_event(v.session, event)
    assert (Cancellation, v.command.id) not in v.rows


@pytest.fixture
def application_specimen(native_grant):
    v = native_grant
    chosen = selection(v)
    calls = []
    actor = UserProfile(id="admin", name="Original actor", email="admin@example.com", role="project_admin")
    from apps.api.app.application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
    authority = HttpFixtureCommandAuthority(invocation_id="original-command", request_digest=acceptance_digest("original-input"))
    state = {"status": "running", "fault": None, "delivery_fault": False, "bound": False}
    def command(_): return chosen, state["status"], authority
    def current(*_):
        calls.append("current")
        if state["status"] != "running": raise HttpFixtureInvalid("original command stopped")
    def bind(inputs, value, *, require_current):
        require_current()
        assert inputs.selection == chosen and value == authority
        calls.append("bind")
        state["bound"] = True
    def finish(value, status, **options):
        assert value == authority
        if status == "completed":
            assert options["history"] == (("setup", None),) and options["inputs"].selection == chosen
            options["require_current"]()
        calls.append("finish:" + status)
        state["status"] = status
        return status
    def cancelled(target, **options):
        options["require_current"]()
        calls.append("cancel-recorded")
        state["status"] = "cancelled"
        return "cancelled"
    async def start(ident):
        assert ident == authority.invocation_id
        calls.append("workflow-start")
        return True
    async def cancel(ident):
        assert ident == authority.invocation_id
        calls.append("workflow-cancel")
        if state["delivery_fault"]: raise RuntimeError("explicit transport outage")
    async def execute(selection, *, require_current, command_authority):
        require_current()
        assert selection == chosen and command_authority == authority and current_user().id == actor.id
        calls.append("execute")
        if state["fault"] is not None: raise state["fault"]
    execution = SimpleNamespace(grants=v.service, execute=execute,
        read=lambda *_args, **options: options["require_current"]() or (("setup", None),))
    repository = SimpleNamespace(command=command, execution=lambda _: (chosen, actor, authority), require_running=current,
        bind=bind, finish=finish, state=lambda *_: {"original": True}, cancel=cancelled,
        preparation_state=lambda *_: None,
        failure_command=lambda _: (state["status"], authority),
        delivery=lambda _: {"status": state["status"], "bound": state["bound"], "authority": authority},
        cancellation_delivered=lambda _: calls.append("delivery-recorded"))
    jobs = HttpFixtureJobApplicationService(execution, repository, SimpleNamespace(start=start, cancel=cancel))
    return SimpleNamespace(jobs=jobs, selected=chosen, authority=authority, actor=actor, calls=calls, state=state, source=v)


def test_dispatch_pins_original_command_before_workflow_and_run_replays_archive(application_specimen):
    v = application_specimen
    asyncio.run(v.jobs.dispatch(v.selected, v.authority.invocation_id))
    assert v.calls.index("bind") < v.calls.index("workflow-start")
    assert asyncio.run(v.jobs.run(v.authority.invocation_id)) == "completed"
    assert v.calls.count("execute") == 1 and v.calls.index("execute") < v.calls.index("finish:completed")
    assert asyncio.run(v.jobs.run(v.authority.invocation_id)) == "completed" and v.calls.count("execute") == 1


def test_unknown_effect_or_cancelled_worker_never_becomes_completion(application_specimen):
    v = application_specimen
    v.state["fault"] = HttpFixtureOutcomeUnknown("explicit unknown original request")
    with pytest.raises(HttpFixtureOutcomeUnknown): asyncio.run(v.jobs.run(v.authority.invocation_id))
    assert "finish:completed" not in v.calls
    v.state["status"] = "cancelled"
    assert asyncio.run(v.jobs.run(v.authority.invocation_id)) == "cancelled" and v.calls.count("execute") == 1


@pytest.mark.parametrize("outage", [False, True])
def test_cancel_is_durable_before_rpc_and_outage_does_not_reopen_it(application_specimen, outage):
    v = application_specimen
    v.state["delivery_fault"] = outage
    target = HttpFixtureJobTarget(project_id=v.selected.project_id, invocation_id=v.authority.invocation_id)
    assert asyncio.run(v.jobs.cancel(target, control_id="control")) == "cancelled"
    assert v.calls.index("cancel-recorded") < v.calls.index("workflow-cancel")
    assert ("delivery-recorded" in v.calls) is not outage


def test_revocation_stops_dispatch_and_cross_project_read(application_specimen):
    v = application_specimen
    v.source.state["revoked"] = True
    with pytest.raises(SourceAccessDenied): asyncio.run(v.jobs.dispatch(v.selected, v.authority.invocation_id))
    assert "bind" not in v.calls and "workflow-start" not in v.calls
    v.source.state["revoked"] = False
    with pytest.raises(SourceAccessDenied): v.jobs.read(HttpFixtureJobTarget(project_id="another", invocation_id=v.authority.invocation_id))


def test_broadcast_hides_payload_result_and_idempotency_fields_and_receipt_reauthorizes():
    calls = []
    policy = HttpFixtureJobReceiptAccess(SimpleNamespace(authorize_receipts=lambda values: calls.extend(values)))
    invocation = ToolInvocation(id="query", tool_id=FIXTURE_QUERY_TOOL, conversation_id="conversation", status="completed",
        input_payload={"project_id": "protected", "invocation_id": "original"}, summary="private details",
        result=ToolResult(invocation_id="query", status="completed", summary="details", http_fixture_job={"protected": True}))
    policy.require_access(invocation)
    policy.require_batch_access((invocation,))
    assert calls == [invocation, invocation]
    projected = policy.broadcast_view(invocation)
    assert projected.input_payload == {} and projected.result is None and "private" not in projected.summary
    assert invocation.result.http_fixture_job == {"protected": True}


def test_late_execute_handler_failure_uses_locked_termination_not_an_unconditional_status_write():
    events, terminations = [], []
    async def dispatch(*_): raise HttpFixtureInvalid("cancelled during original preparation")
    async def fail(ident): terminations.append(ident); return "cancelled"
    async def emit(*args): events.append(args)
    jobs = SimpleNamespace(dispatch=dispatch, fail=fail)
    handler = HttpFixtureJobToolHandler(jobs, SimpleNamespace(emit_tool_status=emit), SimpleNamespace(require_invocation_project_scope=lambda _: None))
    invocation = SimpleNamespace(id="original", tool_id=FIXTURE_COMMAND_TOOL,
        input_payload={"project_id": "project", "grant_id": "grant", "grant_digest": acceptance_digest("grant"), "operation": "setup"})
    asyncio.run(handler.handle(invocation))
    assert terminations == ["original"] and not events


@pytest.mark.parametrize("fault", [HttpFixtureWorkBusy("original worker still owns its lease"),
    RuntimeError("private original database unavailable")])
def test_execute_handler_failure_delivery_never_falls_back_to_unfenced_status_write(fault, caplog):
    events, terminations = [], []
    async def dispatch(*_): raise HttpFixtureInvalid("original command cancelled during preparation")
    async def fail(ident):
        terminations.append(ident)
        raise fault
    async def emit(*args): events.append(args)
    handler = HttpFixtureJobToolHandler(SimpleNamespace(dispatch=dispatch, fail=fail),
        SimpleNamespace(emit_tool_status=emit), SimpleNamespace(require_invocation_project_scope=lambda _: None))
    invocation = SimpleNamespace(id="original", tool_id=FIXTURE_COMMAND_TOOL,
        input_payload={"project_id": "project", "grant_id": "grant", "grant_digest": acceptance_digest("grant"), "operation": "setup"})
    asyncio.run(handler.handle(invocation))
    assert terminations == ["original"] and not events
    assert "termination deferred" in caplog.text and str(fault) not in caplog.text


def test_unknown_temporal_acknowledgement_does_not_terminate_or_redispatch_original(caplog):
    dispatched, events = [], []
    async def dispatch(request, ident):
        dispatched.append((request, ident))
        raise RuntimeError("private unknown Temporal acknowledgement")
    async def fail(_): pytest.fail("unknown acknowledgement must not become a failure write")
    async def emit(*args): events.append(args)
    handler = HttpFixtureJobToolHandler(SimpleNamespace(dispatch=dispatch, fail=fail),
        SimpleNamespace(emit_tool_status=emit), SimpleNamespace(require_invocation_project_scope=lambda _: None))
    invocation = SimpleNamespace(id="original", tool_id=FIXTURE_COMMAND_TOOL,
        input_payload={"project_id": "project", "grant_id": "grant", "grant_digest": acceptance_digest("grant"), "operation": "setup"})
    asyncio.run(handler.handle(invocation))
    assert len(dispatched) == 1 and dispatched[0][1] == "original" and not events
    assert "acknowledgement deferred" in caplog.text and "private unknown" not in caplog.text


def test_execute_scope_denial_uses_only_locked_original_termination():
    events, terminated = [], []
    async def dispatch(*_): pytest.fail("revoked source scope must not dispatch")
    async def fail(ident): terminated.append(ident); return "cancelled"
    async def emit(*args): events.append(args)
    def denied(_): raise SourceAccessDenied("source scope revoked")
    handler = HttpFixtureJobToolHandler(SimpleNamespace(dispatch=dispatch, fail=fail),
        SimpleNamespace(emit_tool_status=emit), SimpleNamespace(require_invocation_project_scope=denied))
    invocation = SimpleNamespace(id="original", tool_id=FIXTURE_COMMAND_TOOL, input_payload={})
    asyncio.run(handler.handle(invocation))
    assert terminated == ["original"] and not events
