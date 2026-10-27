"""Explicit worker protocol doubles; not PG, target execution or business gold."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from threading import Event, Lock

import pytest

from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.application.quality_loop.runner_port import OwnedTargetHttpExecution
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import (
    CASE_CLAIM_SCHEMA, CASE_OUTCOME_SCHEMA, CASE_EXECUTE_TOOL, RunPlanCaseScope, RunPlanCaseLease,
    RunPlanCaseExecutionInvalid, RunPlanCaseWorkBusy, RunPlanCaseWorkLost, RunPlanCaseAlreadyClaimed,
    execution_roster, execution_state, case_claim_id, verify_original_case_command,
)
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.runner.request_wire import runner_request_body, runner_request_hash
from apps.api.tests.test_run_plan_observations import http_plan, protocol_result


def inputs(plan=None):
    plan = plan or http_plan()
    selection = dict(project_id=plan["project_id"], run_id="original-case-attempt", run_plan_id="saved-plan",
        run_plan_artifact_hash=acceptance_digest("plan archive"), plan_digest=plan["plan_digest"], timeout_ms=5000,
        build_binding_id="original-build-binding", build_binding_artifact_hash=acceptance_digest("build binding"),
        environment_record_id="original-environment", environment_record_artifact_hash=acceptance_digest("native inventory"),
        locator_record_id="original-locators", locator_record_artifact_hash=acceptance_digest("locator record"),
        fixture_setups=[dict(case_id=item["case_id"], invocation_id="setup-" + str(index))
            for index, item in enumerate(plan["prepared"]["cases"])])
    now = datetime.now(timezone.utc)
    payload = {**deepcopy(selection), "confirmed_by_user": True, "confirmed_actor_id": "qa-owner",
        "confirmed_at": now.isoformat()}
    snapshot = dict(id="independent-case-command", tool_id=CASE_EXECUTE_TOOL, status="running", input_payload=payload)
    scope = RunPlanCaseScope(**{key: selection[key] for key in
        ("project_id", "run_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "timeout_ms")},
        invocation_id=snapshot["id"], actor_id="qa-owner", source_scope_digest=acceptance_digest("current source permissions"),
        request_digest=acceptance_digest(selection), command_digest=acceptance_digest({"tool_id": CASE_EXECUTE_TOOL,
            "input_payload": payload}), environment_id=plan["selection"]["environment"]["environment_id"],
        target_artifact_hash=plan["selection"]["target_build"]["artifact_hash"], inventory_hash=acceptance_digest("owned inventory"),
        image_revision_id=plan["source_pin"]["image_revision_id"], manifest_id=plan["source_pin"]["manifest_id"], selection=selection)
    return plan, scope, snapshot, now


class Journal:
    """Deterministic protocol double; lease time/restart are deliberately simulated."""
    def __init__(self):
        self.lock, self.scope, self.roster, self.lease = Lock(), None, None, None
        self.claims, self.outcomes, self.cancelled, self.expired = [], [], False, False
        self.fail_commit, self.fail_renew, self.on_inspect = False, False, None

    def acquire(self, scope, roster, owner_id, *, require_current):
        require_current()
        with self.lock:
            if self.scope is not None and (self.scope != scope or self.roster != roster):
                raise RunPlanCaseExecutionInvalid("rebound")
            if self.lease is not None and not self.expired:
                raise RunPlanCaseWorkBusy("live owner")
            if self.cancelled:
                raise RunPlanCaseWorkLost("cancelled")
            self.scope, self.roster = deepcopy(scope), deepcopy(roster)
            self.lease = RunPlanCaseLease(scope, owner_id, self.lease.epoch + 1 if self.lease else 1)
            self.expired = False
            return self.lease

    def require(self, lease, *, require_current):
        require_current()
        if self.cancelled or self.expired or lease != self.lease:
            raise RunPlanCaseWorkLost("no original live ownership")

    def renew(self, lease, *, require_current):
        if self.fail_renew:
            raise RunPlanCaseWorkLost("heartbeat failed")
        self.require(lease, require_current=require_current)

    def inspect(self, scope, roster, *, require_access):
        require_access()
        if self.scope != scope or self.roster != roster:
            raise RunPlanCaseExecutionInvalid("rebound")
        value = deepcopy(dict(claims=self.claims, outcomes=self.outcomes, cancelled=self.cancelled))
        if self.on_inspect:
            self.on_inspect()
        return value

    def claim(self, lease, case, *, require_current):
        self.require(lease, require_current=require_current)
        with self.lock:
            if any(item["case_id"] == case["case_id"] for item in self.claims):
                raise RunPlanCaseAlreadyClaimed("existing original slot")
            value = dict(schema=CASE_CLAIM_SCHEMA, claim_id=case_claim_id(lease.scope, case["case_id"]),
                project_id=lease.scope.project_id, work_id=lease.work_id, scope_digest=lease.scope.digest,
                owner_id=lease.owner_id, epoch=lease.epoch, recorded_at="2026-10-13T10:00:00+00:00", **deepcopy(case))
            self.claims.append(value)
            return deepcopy(value)

    def complete(self, lease, claim, *, artifact_ref, artifact_hash, observation, require_current):
        self.require(lease, require_current=require_current)
        if self.fail_commit:
            raise RuntimeError("late outbox failure")
        assert claim in self.claims and claim["owner_id"] == lease.owner_id and claim["epoch"] == lease.epoch
        value = dict(schema=CASE_OUTCOME_SCHEMA, project_id=lease.scope.project_id, claim_id=claim["claim_id"],
            case_id=claim["case_id"], dispatch_digest=acceptance_digest(claim), recorded_at="2026-10-13T10:00:01+00:00",
            status=observation["status"], observation_digest=observation["observation_digest"],
            artifact_ref=artifact_ref, artifact_hash=artifact_hash)
        self.outcomes.append(value)
        return deepcopy(value)


class Artifacts:
    def __init__(self):
        self.values, self.fail_write, self.on_write = {}, False, None

    def put(self, project_id, payload):
        if self.fail_write:
            raise RuntimeError("private archive unavailable")
        digest = acceptance_digest(payload)
        self.values[digest] = json.loads(json.dumps(payload))
        if self.on_write:
            self.on_write()
        return "private-case://" + digest, digest

    def read(self, project_id, ref, digest):
        assert ref == "private-case://" + digest
        return deepcopy(self.values[digest])


class Runner:
    def __init__(self):
        self.commands, self.failure, self.failed_case, self.block = [], None, None, None
        self.entered, self.release = Event(), Event()
        self.change_wire = False

    def execute_owned_http(self, command, *, environment_id, artifact_hash, inventory_hash, require_work):
        require_work()
        self.commands.append(deepcopy(command))
        self.entered.set()
        if self.block:
            self.release.wait(timeout=3)
            require_work()
        if self.failure:
            raise self.failure
        payload = json.loads(json.dumps(asdict(protocol_result(command, failed=command.us_id == self.failed_case))))
        result = HttpAutomationRunner._result_from_payload(command, payload, request_hash=runner_request_hash(command))
        return OwnedTargetHttpExecution(result, b"{}" if self.change_wire else runner_request_body(command),
            json.dumps(payload).encode(), environment_id, inventory_hash)


def service():
    runner, journal, artifacts = Runner(), Journal(), Artifacts()
    return RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), journal, artifacts), runner, journal, artifacts


def run(app, plan, scope, snapshot, now):
    return asyncio.run(app.execute(plan, scope, require_current=lambda: verify_original_case_command(
        scope, snapshot, scope.selection, now=now)))


def test_full_original_roster_executes_once_and_read_reverifies_every_step_oracle():
    plan, scope, snapshot, now = inputs()
    original = deepcopy(plan)
    app, runner, journal, _ = service()
    result = run(app, plan, scope, snapshot, now)
    assert result["state"]["state"] == "observed"
    assert len(runner.commands) == len(journal.claims) == len(journal.outcomes) == len(plan["prepared"]["cases"])
    for case, observed in zip(plan["prepared"]["cases"], result["observations"]):
        assert observed["case_id"] == case["case_id"]
        assert {item["oracle_digest"] for item in observed["oracles"]} == {item["oracle_digest"] for item in case["assertions"]}
    assert result["state"]["automated_count"] == result["state"]["executed_on_target_count"] == result["state"]["passed_count"] == 0
    assert not result["state"]["business_coverage_verified"] and plan == original
    journal.expired = True
    assert run(app, plan, scope, snapshot, now) == result
    assert journal.lease.epoch == 2 and len(runner.commands) == len(journal.outcomes)


def test_transaction_owned_journal_never_reenters_its_worker_lease_guard():
    class NonReentrantJournal(Journal):
        inside_transaction = False

        def require(self, lease, *, require_current):
            assert not self.inside_transaction, "worker guard recursively acquired the journal transaction"
            return super().require(lease, require_current=require_current)

        def transaction_guard(self, require_current):
            def guarded():
                self.inside_transaction = True
                try:
                    require_current()
                finally:
                    self.inside_transaction = False
            return guarded

        def claim(self, lease, case, *, require_current):
            return super().claim(lease, case, require_current=self.transaction_guard(require_current))

        def complete(self, lease, claim, **kwargs):
            return super().complete(lease, claim, **{**kwargs,
                "require_current": self.transaction_guard(kwargs["require_current"])})

    class NestedGuardContrast(RunPlanCaseExecutionApplicationService):
        def _execute(self, plan, scope, lease, require_work, require_current):
            return super()._execute(plan, scope, lease, require_work, require_work)

    plan, scope, snapshot, now = inputs()
    contrast = NestedGuardContrast(Runner(), OwnedHttpFixtureObservationVerifier(), NonReentrantJournal(), Artifacts())
    with pytest.raises(AssertionError, match="recursively acquired"):
        run(contrast, plan, scope, snapshot, now)
    runner, journal = Runner(), NonReentrantJournal()
    app = RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), journal, Artifacts())
    result = run(app, plan, scope, snapshot, now)
    assert result["state"]["state"] == "observed"
    assert len(runner.commands) == len(journal.claims) == len(journal.outcomes) == len(plan["prepared"]["cases"])


def test_failed_case_does_not_drop_other_cases_or_claim_business_pass():
    plan, scope, snapshot, now = inputs()
    app, runner, journal, _ = service()
    runner.failed_case = plan["prepared"]["cases"][0]["case_id"]
    result = run(app, plan, scope, snapshot, now)
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["oracles"][0]["status"] == "failed"
    assert result["state"]["state"] == "observed" and len(journal.outcomes) == len(plan["prepared"]["cases"])
    assert result["state"]["passed_count"] == 0


@pytest.mark.parametrize("fault", ["transport", "native_wire"])
def test_claim_without_verified_output_blocks_restart_and_remaining_cases(fault):
    plan, scope, snapshot, now = inputs()
    app, runner, journal, _ = service()
    if fault == "transport": runner.failure = TimeoutError("possibly dispatched")
    else: runner.change_wire = True
    result = run(app, plan, scope, snapshot, now)
    assert result["state"]["state"] == "outcome_unknown" and len(runner.commands) == 1
    assert result["state"]["not_dispatched_case_count"] == len(plan["prepared"]["cases"]) - 1
    runner.failure, runner.change_wire, journal.expired = None, False, True
    assert run(app, plan, scope, snapshot, now)["state"]["state"] == "outcome_unknown"
    assert len(runner.commands) == 1 and journal.outcomes == []
    journal.cancelled = True
    assert app.read(plan, scope, require_access=lambda: None)["state"]["state"] == "outcome_unknown"


@pytest.mark.parametrize("fault", ["archive", "commit", "revoked_after_archive"])
def test_late_failure_preserves_original_claim_and_never_resends(fault):
    plan, scope, snapshot, now = inputs()
    app, runner, journal, artifacts = service()
    if fault == "archive": artifacts.fail_write = True
    elif fault == "commit": journal.fail_commit = True
    else: artifacts.on_write = lambda: setattr(journal, "cancelled", True)
    with pytest.raises((RuntimeError, RunPlanCaseWorkLost)):
        run(app, plan, scope, snapshot, now)
    assert len(journal.claims) == len(runner.commands) == 1 and journal.outcomes == []
    assert app.read(plan, scope, require_access=lambda: None)["state"]["state"] == "outcome_unknown"


@pytest.mark.parametrize("fault", ["body", "wire", "oracle", "scope", "result_field"])
def test_historical_native_archive_is_reverified_and_not_repaired(fault):
    plan, scope, snapshot, now = inputs()
    app, runner, journal, artifacts = service()
    run(app, plan, scope, snapshot, now)
    outcome = journal.outcomes[0]
    value = artifacts.values[outcome["artifact_hash"]]
    if fault == "body": value["result"]["artifacts"][0]["content_base64"] = "d3Jvbmc="
    elif fault == "wire": value["result_body"] = "e30="
    elif fault == "oracle": value["observation"]["oracles"][0]["oracle_digest"] = acceptance_digest("wrong")
    elif fault == "scope": value["scope_digest"] = acceptance_digest("wrong")
    else: value["result"]["execution_authorized"] = True
    # Even rehashing the untrusted artifact cannot alter its immutable outcome pin.
    with pytest.raises(RunPlanCaseExecutionInvalid): app.read(plan, scope, require_access=lambda: None)
    assert len(runner.commands) == len(journal.outcomes)


@pytest.mark.parametrize("fault", ["tool", "actor", "confirmation", "future", "expired", "selection", "coordination"])
def test_independent_original_command_rejects_fixture_permission_and_mutation(fault):
    plan, scope, snapshot, now = inputs()
    if fault == "tool": snapshot["tool_id"] = "quality.http_fixture.execute"
    elif fault == "actor": snapshot["input_payload"]["confirmed_actor_id"] = "other"
    elif fault == "confirmation": snapshot["input_payload"]["confirmed_by_user"] = 1
    elif fault == "future": now -= timedelta(seconds=1)
    elif fault == "expired": now += timedelta(seconds=901)
    elif fault == "selection": scope.selection["timeout_ms"] += 1
    else: snapshot["input_payload"]["agent_goal_id"] = "new"
    app, runner, journal, _ = service()
    with pytest.raises((RunPlanCaseExecutionInvalid, ValueError)):
        run(app, plan, scope, snapshot, now)
    assert runner.commands == [] and journal.claims == []


@pytest.mark.parametrize("field,value", [("epoch", True), ("epoch", 0), ("epoch", 2147483648),
    ("owner_id", ""), ("owner_id", " \n"), ("owner_id", "\ud800")])
def test_lease_rejects_fabricated_ownership(field, value):
    _plan, scope, _snapshot, _now = inputs()
    with pytest.raises(RunPlanCaseExecutionInvalid): RunPlanCaseLease(**{**dict(scope=scope, owner_id="owner", epoch=1), field: value})


@pytest.mark.parametrize("field", ["invocation_id", "actor_id", "plan_digest", "target_artifact_hash", "inventory_hash"])
def test_new_scope_cannot_create_another_slot_for_same_original_attempt(field):
    plan, scope, _snapshot, _now = inputs()
    changes = {field: acceptance_digest("changed") if field.endswith(("hash", "digest")) else "other"}
    if field == "plan_digest":
        changes["selection"] = {**scope.selection, **changes}
        changes["request_digest"] = acceptance_digest(changes["selection"])
    changed = replace(scope, **changes)
    assert changed.work_id == scope.work_id and changed.digest != scope.digest
    assert case_claim_id(changed, plan["prepared"]["cases"][0]["case_id"]) == case_claim_id(scope, plan["prepared"]["cases"][0]["case_id"])


def test_concurrent_worker_is_rejected_and_cancellation_joins_owned_thread():
    plan, scope, snapshot, now = inputs()
    app, runner, journal, _ = service()
    runner.block = True

    async def scenario():
        guard = lambda: verify_original_case_command(scope, snapshot, scope.selection, now=now)
        task = asyncio.create_task(app.execute(plan, scope, require_current=guard, renew_seconds=.01))
        await asyncio.to_thread(runner.entered.wait, 2)
        with pytest.raises(RunPlanCaseWorkBusy):
            await app.execute(plan, scope, require_current=guard)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        runner.release.set()
        with pytest.raises(asyncio.CancelledError): await task

    asyncio.run(scenario())
    assert len(runner.commands) == len(journal.claims) == 1 and not journal.outcomes
    assert app.read(plan, scope, require_access=lambda: None)["state"]["state"] == "outcome_unknown"


def test_history_change_mid_read_is_not_returned_as_a_stable_receipt():
    plan, scope, snapshot, now = inputs()
    app, _runner, journal, _artifacts = service()
    run(app, plan, scope, snapshot, now)
    journal.on_inspect = lambda: setattr(journal, "cancelled", True)
    with pytest.raises(RunPlanCaseWorkLost): app.read(plan, scope, require_access=lambda: None)


def test_roster_does_not_accept_missing_or_reordered_fixture_setup_pins():
    plan, scope, _snapshot, _now = inputs()
    for setups in (scope.selection["fixture_setups"][:-1], list(reversed(scope.selection["fixture_setups"]))):
        selection = {**scope.selection, "fixture_setups": setups}
        with pytest.raises(RunPlanCaseExecutionInvalid):
            execution_roster(plan, replace(scope, selection=selection, request_digest=acceptance_digest(selection)))


@pytest.mark.parametrize("fault", ["epoch_bool", "ordinal_bool", "project", "extra_authority", "scope_digest", "duplicate"])
def test_reserved_fact_cannot_be_rehashed_into_another_scope_or_authority(fault):
    plan, scope, snapshot, now = inputs()
    app, runner, journal, _artifacts = service()
    runner.failure = TimeoutError("unknown")
    run(app, plan, scope, snapshot, now)
    claim = journal.claims[0]
    if fault == "epoch_bool": claim["epoch"] = True
    elif fault == "ordinal_bool": claim["ordinal"] = False
    elif fault == "project": claim["project_id"] = "other"
    elif fault == "extra_authority": claim["execution_authorized"] = True
    elif fault == "scope_digest": claim["scope_digest"] = acceptance_digest("wrong")
    else: journal.claims.append(deepcopy(claim))
    with pytest.raises(RunPlanCaseExecutionInvalid): app.read(plan, scope, require_access=lambda: None)
    assert len(runner.commands) == 1


@pytest.mark.parametrize("fault", ["duplicate", "no_claim", "dispatch_digest", "project", "authority", "status"])
def test_native_outcome_must_match_one_original_dispatch(fault):
    plan, scope, snapshot, now = inputs()
    app, _runner, journal, _artifacts = service()
    run(app, plan, scope, snapshot, now)
    value = journal.outcomes[0]
    if fault == "duplicate": journal.outcomes.append(deepcopy(value))
    elif fault == "no_claim": journal.claims.pop(0)
    elif fault == "dispatch_digest": value["dispatch_digest"] = acceptance_digest("wrong")
    elif fault == "project": value["project_id"] = "other"
    elif fault == "authority": value["execution_authorized"] = True
    else: value["status"] = "completed"
    with pytest.raises(RunPlanCaseExecutionInvalid): app.read(plan, scope, require_access=lambda: None)


def test_archive_and_outcome_rehash_cannot_hide_wrong_physical_response_bytes():
    plan, scope, snapshot, now = inputs()
    app, _runner, journal, artifacts = service()
    run(app, plan, scope, snapshot, now)
    outcome = journal.outcomes[0]
    value = deepcopy(artifacts.values[outcome["artifact_hash"]])
    value["result"]["artifacts"][0]["content_base64"] = "d3Jvbmc="
    digest = acceptance_digest(value)
    artifacts.values[digest] = value
    outcome["artifact_ref"], outcome["artifact_hash"] = "private-case://" + digest, digest
    with pytest.raises(RunPlanCaseExecutionInvalid): app.read(plan, scope, require_access=lambda: None)


@pytest.mark.parametrize("value", [True, 0, -1, 45, float("nan"), float("inf")])
def test_invalid_heartbeat_interval_cannot_acquire_or_dispatch(value):
    plan, scope, _snapshot, _now = inputs()
    app, runner, journal, _artifacts = service()
    with pytest.raises(RunPlanCaseExecutionInvalid):
        asyncio.run(app.execute(plan, scope, require_current=lambda: None, renew_seconds=value))
    assert journal.lease is None and not runner.commands


def test_lost_heartbeat_joins_transport_thread_before_reporting_loss():
    plan, scope, _snapshot, _now = inputs()
    app, runner, journal, _artifacts = service()
    runner.block, journal.fail_renew = True, True

    async def scenario():
        task = asyncio.create_task(app.execute(plan, scope, require_current=lambda: None, renew_seconds=.01))
        assert await asyncio.to_thread(runner.entered.wait, 2)
        await asyncio.sleep(.04)
        assert not task.done()
        runner.release.set()
        with pytest.raises(RunPlanCaseWorkLost): await task

    asyncio.run(scenario())
    assert len(runner.commands) == 1 and not journal.outcomes


def test_current_permission_rejection_precedes_historical_archive_access():
    plan, scope, snapshot, now = inputs()
    app, _runner, journal, artifacts = service()
    run(app, plan, scope, snapshot, now)
    artifacts.values.clear()

    def revoked():
        raise PermissionError("original source revoked")

    with pytest.raises(PermissionError): app.read(plan, scope, require_access=revoked)
    assert len(journal.outcomes) == len(plan["prepared"]["cases"])


def test_explicit_v2_plan_keeps_capture_actions_and_original_oracles_in_full_roster():
    from apps.api.tests.test_http_binding_scripts import binding_plan
    plan, scope, _snapshot, _now = inputs(binding_plan())
    app, _runner, _journal, _artifacts = service()
    roster = execution_roster(plan, scope)
    commands = app._commands(plan, scope)
    assert len(roster) == len(commands) == len(plan["prepared"]["cases"])
    for case in roster:
        _job, command = commands[case["case_id"]]
        assert command.http_protocol == "nasus.runner-http-execution.v2"
        assert command.steps[1]["action"] == "capture_json"
        script = next(item for item in plan["proposal"]["scripts"] if item["case_id"] == case["case_id"])
        assert list(command.steps) == script["actions"]
        assert len(script["assertions"]) == len(next(item for item in plan["prepared"]["cases"]
            if item["case_id"] == case["case_id"])["assertions"])


def test_historical_terminal_command_is_readable_after_expiry_but_cannot_dispatch():
    _plan, scope, snapshot, now = inputs()
    snapshot["status"] = "cancelled"
    assert verify_original_case_command(scope, snapshot, scope.selection, historical=True, now=now + timedelta(days=1))
    with pytest.raises(RunPlanCaseExecutionInvalid):
        verify_original_case_command(scope, snapshot, scope.selection, now=now + timedelta(days=1))


def test_late_cancellation_cannot_replace_the_complete_original_observations():
    plan, scope, snapshot, now = inputs()
    app, runner, journal, _artifacts = service()
    original = run(app, plan, scope, snapshot, now)
    journal.cancelled = True
    value = app.read(plan, scope, require_access=lambda: None)
    assert value["state"]["state"] == "observed" and value["state"]["cancelled"] is True
    assert value["observations"] == original["observations"]
    assert len(runner.commands) == len(plan["prepared"]["cases"])
