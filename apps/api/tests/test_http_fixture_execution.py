"""Private worker scheduling specimens, not native target or canonical execution."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from threading import Event, get_ident
import time
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope, current_user
from apps.api.app.application.quality_loop.http_fixture_execution import (
    HttpFixtureExecutionApplicationService, HttpFixtureExecutionSelection,
    HttpFixtureWorkerRuntime,
)
from apps.api.app.application.quality_loop.http_fixture_grants import HttpFixtureGrantRequest
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkLost, HttpFixtureWorkLease, fixture_work_digest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


def selection(v, *, operation="setup", command="original-worker-grant"):
    request = HttpFixtureGrantRequest.model_validate({**v.request.model_dump(mode="json"), "operation": operation})
    metadata = v.service.issue(request, invocation_id=command)
    return HttpFixtureExecutionSelection(project_id=request.project_id, grant_id=metadata["record_id"],
        grant_digest=metadata["grant_digest"], operation=operation)


def test_worker_resolves_original_manifest_parent_instance_and_one_operation(native_grant):
    v = native_grant
    chosen = selection(v)
    old = deepcopy((v.saved, v.manifest, v.environment, v.state["issued"]))
    inputs = v.service.execution_inputs(chosen, live=True)
    assert inputs.selection == chosen and inputs.scope == inputs.consent.scope
    assert inputs.parent.run_plan_id == v.saved["metadata"]["run_plan_id"]
    assert inputs.parent.run_plan_artifact_hash == v.saved["metadata"]["artifact_hash"]
    assert inputs.scope.inventory_hash == v.environment["metadata"]["inventory_hash"]
    assert inputs.scope.inventory_hash != inputs.native_environment["operator_policy_digest"]
    assert inputs.manifest == v.manifest and v.state["live"] == 1
    inputs.manifest["setup_steps"][0]["path"] = "/caller-mutated"
    assert (v.saved, v.manifest, v.environment, v.state["issued"]) == old
    assert v.service.execution_inputs(chosen, live=True).manifest == v.manifest


@pytest.mark.parametrize("field,value", [("operation", "both"), ("operation", True), ("grant_digest", "bad"),
    ("grant_id", ""), ("project_id", 1), ("approved", True), ("base_url", "https://example.com"),
    ("owner_id", "user-selected-worker")])
def test_request_cannot_choose_a_target_worker_or_combined_operation(native_grant, field, value):
    chosen = selection(native_grant).model_dump(mode="json")
    chosen[field] = value
    with pytest.raises(ValueError): HttpFixtureExecutionSelection.model_validate(chosen)


@pytest.mark.parametrize("change", ["digest", "operation", "legacy", "revoked", "stale", "expired"])
def test_invalid_original_consent_stops_before_worker_acquisition(native_grant, monkeypatch, change):
    v = native_grant
    chosen = selection(v)
    if change == "digest": chosen = chosen.model_copy(update={"grant_digest": acceptance_digest("another")})
    elif change == "operation": chosen = chosen.model_copy(update={"operation": "cleanup"})
    elif change == "legacy":
        payload = v.request.model_dump(mode="json")
        for key in ("policy_revision", "environment_record_id", "environment_record_artifact_hash"): payload.pop(key)
        legacy = v.service.issue(HttpFixtureGrantRequest.model_validate(payload), invocation_id="legacy-worker-grant")
        chosen = chosen.model_copy(update={"grant_id": legacy["record_id"], "grant_digest": legacy["grant_digest"]})
    elif change == "revoked": v.state["revoked"] = True
    elif change == "stale": v.saved["current_use"]["inputs_current"] = False
    else:
        def expired(*args, **kwargs): raise PermissionError("original grant expired")
        monkeypatch.setattr(v.service.repository, "require_live", expired)
    calls = []
    factory = SimpleNamespace(create=lambda *args, **kwargs: calls.append(True))
    app = HttpFixtureExecutionApplicationService(v.service, factory)
    with pytest.raises((RunPlanIntegrityError, RunPlanChanged, SourceAccessDenied, PermissionError)):
        asyncio.run(app.execute(chosen, require_current=lambda: None))
    assert not calls


def test_history_after_expiry_is_read_only_and_does_not_renew_consent(native_grant, monkeypatch):
    v = native_grant
    chosen = selection(v)
    calls = []
    def expired(*args, **kwargs): pytest.fail("historical read must not consume or renew a grant")
    monkeypatch.setattr(v.service.repository, "require_live", expired)
    app = HttpFixtureExecutionApplicationService(v.service, SimpleNamespace(
        history=lambda inputs, **kwargs: calls.append(inputs) or (("setup", None),),
        create=lambda *args, **kwargs: pytest.fail("historical read cannot acquire a worker")))
    assert app.read(chosen, require_current=lambda: None) == (("setup", None),)
    assert len(calls) == 1 and v.state["live"] == 0


@pytest.mark.parametrize("field,value", [("parent_digest", acceptance_digest("another-parent")),
    ("inventory_hash", acceptance_digest("another-instance")), ("case_id", "another-case")])
def test_resolved_inputs_cannot_be_rebound_to_a_new_scope(native_grant, field, value):
    v = native_grant
    inputs = v.service.execution_inputs(selection(v), live=True)
    with pytest.raises(HttpFixtureInvalid): replace(inputs, scope=replace(inputs.scope, **{field: value}))


@pytest.mark.parametrize("field,value", [("record_id", ""), ("artifact_hash", "other"),
    ("inventory_hash", True), ("operator_policy_digest", "bad"), ("approved", True)])
def test_worker_native_pin_rejects_invalid_identity_digest_and_authority_fields(native_grant, field, value):
    v = native_grant
    inputs = v.service.execution_inputs(selection(v), live=True)
    with pytest.raises(HttpFixtureInvalid):
        replace(inputs, native_environment={**inputs.native_environment, field: value})


class RuntimeSpecimen:
    def __init__(self, *, gate=None, renew_fault=False):
        self.calls, self.commits, self.checks, self.renewals = [], [], [], []
        self.started, self.finished = Event(), Event()
        self.gate, self.renew_fault = gate, renew_fault

    def create(self, inputs, *, owner_id, require_current):
        require_current()
        lease = HttpFixtureWorkLease(inputs.scope, inputs.selection.operation, owner_id, 1,
            fixture_work_digest(inputs.scope, inputs.selection.operation))
        def checked(value):
            assert value == lease
            require_current()
            self.checks.append(get_ident())
        def renew(value, *, require_current):
            checked(value)
            require_current()
            self.renewals.append(get_ident())
            if self.renew_fault: raise HttpFixtureWorkLost("explicit specimen takeover")
        def operate(scope, manifest, *, require_work):
            self.calls.append((inputs.selection.operation, scope, deepcopy(manifest), current_user().id, get_ident()))
            self.started.set()
            try:
                until = time.monotonic() + 0.09
                while self.gate is not None or time.monotonic() < until:
                    require_work()
                    if self.gate is not None and self.gate.is_set(): break
                    time.sleep(0.003)
                require_work()
                self.commits.append(scope.digest)
                return "original-result"
            finally:
                self.finished.set()
        return HttpFixtureWorkerRuntime(SimpleNamespace(prepare=operate, cleanup=operate),
            SimpleNamespace(require=checked, renew=renew), lease)


@pytest.mark.parametrize("operation", ["setup", "cleanup"])
def test_async_worker_keeps_actor_heartbeat_and_original_operation_off_event_loop(native_grant, operation):
    v = native_grant
    chosen = selection(v, operation=operation)
    factory = RuntimeSpecimen()
    app = HttpFixtureExecutionApplicationService(v.service, factory)
    actor = UserProfile(id="original-actor", name="Worker", email="worker@example.com", role="project_admin")
    async def run():
        loop_thread = get_ident()
        with actor_scope(actor):
            value = await app.execute(chosen, require_current=lambda: None, renew_seconds=0.01)
        assert value == "original-result" and factory.renewals
        assert factory.calls[0][0] == operation and factory.calls[0][3] == actor.id
        assert factory.calls[0][4] != loop_thread and all(thread != loop_thread for thread in factory.checks)
        assert len(factory.calls) == len(factory.commits) == 1 and factory.finished.is_set()
    asyncio.run(run())


@pytest.mark.parametrize("repeat", [False, True])
def test_cancellation_joins_the_owned_thread_without_a_late_commit(native_grant, repeat):
    v = native_grant
    chosen = selection(v)
    factory = RuntimeSpecimen(gate=Event())
    app = HttpFixtureExecutionApplicationService(v.service, factory)
    async def run():
        actor = UserProfile(id="original-actor", name="Worker", email="worker@example.com", role="project_admin")
        with actor_scope(actor):
            task = asyncio.create_task(app.execute(chosen, require_current=lambda: None, renew_seconds=0.01))
            try:
                assert await asyncio.to_thread(factory.started.wait, 2)
                task.cancel()
                if repeat:
                    await asyncio.sleep(0)
                    task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                assert factory.finished.is_set() and not factory.commits and len(factory.calls) == 1
                await asyncio.sleep(0.01)
                assert not factory.commits
            finally:
                factory.gate.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_lost_lease_joins_adapter_and_never_dispatches_a_replacement(native_grant):
    v = native_grant
    chosen = selection(v)
    factory = RuntimeSpecimen(gate=Event(), renew_fault=True)
    app = HttpFixtureExecutionApplicationService(v.service, factory)
    actor = UserProfile(id="original-actor", name="Worker", email="worker@example.com", role="project_admin")
    async def run():
        with actor_scope(actor):
            with pytest.raises(HttpFixtureWorkLost):
                await app.execute(chosen, require_current=lambda: None, renew_seconds=0.01)
        assert factory.finished.is_set() and not factory.commits and len(factory.calls) == 1
    asyncio.run(run())


def test_cancelled_slow_input_resolution_cannot_create_a_worker(native_grant):
    v = native_grant
    chosen = selection(v)
    started, returned = Event(), Event()
    factory = RuntimeSpecimen()
    original = v.service.execution_inputs
    def slow(*args, **kwargs):
        started.set()
        time.sleep(0.04)
        try: return original(*args, **kwargs)
        finally: returned.set()
    app = HttpFixtureExecutionApplicationService(SimpleNamespace(execution_inputs=slow), factory)
    async def run():
        task = asyncio.create_task(app.execute(chosen, require_current=lambda: None))
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert returned.is_set() and not factory.calls and not factory.commits
    asyncio.run(run())
