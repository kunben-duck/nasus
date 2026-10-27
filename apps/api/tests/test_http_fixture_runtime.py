"""Actual factory wiring with explicit repository/Runner scheduling specimens."""
import logging
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionStopped
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkLease, fixture_work_digest
from apps.api.app.domain.quality_loop.http_fixture_grant import grant_metadata
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner import http_fixture_runtime as runtime
from apps.api.tests.test_http_fixture_execution import selection
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


def factory(v, storage=None, *, runner=None, commands=None):
    return runtime.OwnedHttpFixtureRuntimeFactory(v.service, v.plans, v.records, None,
        storage or SimpleNamespace(config=SimpleNamespace(s3_enabled=True)), runner=runner, commands=commands)


def live_inputs(v, monkeypatch):
    inputs = v.service.execution_inputs(selection(v), live=True)
    def live(*args, **kwargs):
        v.service.authorization.require_current(inputs.access_scope)
        v.state["live"] += 1
        return grant_metadata(v.state["issued"][inputs.selection.grant_id])
    monkeypatch.setattr(v.service.repository, "require_live", live)
    return inputs


def test_unconfigured_factory_can_be_composed_but_no_operation_can_use_local_storage(native_grant, monkeypatch):
    v = native_grant
    inputs = live_inputs(v, monkeypatch)
    value = factory(v, SimpleNamespace(config=SimpleNamespace(s3_enabled=False)))
    with pytest.raises(HttpFixtureInvalid, match="private S3"):
        value.create(inputs, owner_id="worker", require_current=lambda: None)
    with pytest.raises(HttpFixtureInvalid, match="private S3"):
        value.history(inputs, require_current=lambda: None)


def test_missing_operator_node_configuration_fails_before_any_pg_lease(native_grant, monkeypatch):
    inputs = live_inputs(native_grant, monkeypatch)
    monkeypatch.delenv("NASUS_HTTP_FIXTURE_NODE", raising=False)
    monkeypatch.setattr(runtime, "PostgresHttpFixtureDispatchJournal",
        lambda *args, **kwargs: pytest.fail("missing operator Node must stop before creating a PG journal"))
    with pytest.raises(ValueError):
        factory(native_grant).create(inputs, owner_id="worker", require_current=lambda: None)


def test_factory_binds_original_worker_and_consent_and_rechecks_at_runner_boundary(native_grant, monkeypatch):
    v = native_grant
    inputs = live_inputs(v, monkeypatch)
    created, leases, runner_calls = [], [], []
    class Journal:
        def __init__(self, access, artifacts, **options):
            self.access, self.artifacts = access, artifacts
            created.append(options)
    class Repository:
        def __init__(self, journal): self.journal = journal
        def acquire(self, scope, operation, owner_id, *, require_current):
            require_current()
            lease = HttpFixtureWorkLease(scope, operation, owner_id, 1, fixture_work_digest(scope, operation))
            leases.append(lease)
            return lease
        def fence(self, lease): return lease
        def require(self, lease): assert lease == leases[0]
        def renew(self, lease, *, require_current):
            require_current()
            assert lease == leases[0]
    def execute(command, **options):
        options["require_work"]()
        runner_calls.append(command)
        return "original-output"
    monkeypatch.setattr(runtime, "PostgresHttpFixtureDispatchJournal", Journal)
    monkeypatch.setattr(runtime, "PostgresHttpFixtureWorkRepository", Repository)
    assembled = factory(v, runner=SimpleNamespace(execute_owned_http=execute)).create(inputs,
        owner_id="original-worker", require_current=lambda: None)
    assert assembled.lease == leases[0] and assembled.lease.owner_id == "original-worker"
    assert created[1]["work_fence"] == assembled.lease
    assert created[1]["consent_fence"].consent == inputs.consent
    assert created[0]["actor_id"] == created[1]["actor_id"] == inputs.consent.actor_id
    options = dict(environment_id=inputs.scope.environment_id, artifact_hash=inputs.scope.artifact_hash,
        inventory_hash=inputs.scope.inventory_hash, require_work=lambda: None)
    assert assembled.lifecycle.runner.execute_owned_http("original-command", **options) == "original-output"
    v.state["revoked"] = True
    with pytest.raises(SourceAccessDenied): assembled.lifecycle.runner.execute_owned_http("new-command", **options)
    assert runner_calls == ["original-command"] and len(leases) == 1


def test_history_resolves_only_original_phases_without_node_lease_or_live_consent(native_grant, monkeypatch):
    v = native_grant
    inputs = live_inputs(v, monkeypatch)
    observed = []
    class Journal:
        def __init__(self, access, artifacts, **options):
            assert options == {"actor_id": inputs.access_scope.actor_id}
        def inspect(self, scope, phase, *, read_only):
            assert scope == inputs.scope and read_only is True
            observed.append(phase)
            return None
    monkeypatch.setattr(runtime, "PostgresHttpFixtureDispatchJournal", Journal)
    monkeypatch.setattr(runtime, "PostgresHttpFixtureWorkRepository",
        lambda *args: pytest.fail("historical reads cannot acquire or renew a lease"))
    monkeypatch.setattr(runtime, "ConfiguredOwnedTargetHttpRunner",
        lambda **kwargs: pytest.fail("historical reads cannot construct a Runner"))
    monkeypatch.setattr(v.service.repository, "require_live",
        lambda *args, **kwargs: pytest.fail("expired original history cannot renew permission"))
    assert factory(v).history(inputs, require_current=lambda: None) == (("setup", None),)
    assert observed == ["setup"]


def test_stopped_worker_cannot_create_runtime_or_use_an_existing_runner(native_grant, monkeypatch):
    inputs = live_inputs(native_grant, monkeypatch)
    def stopped(): raise HttpFixtureExecutionStopped("original operation stopped")
    with pytest.raises(HttpFixtureExecutionStopped):
        factory(native_grant).create(inputs, owner_id="worker", require_current=stopped)


def test_explicit_command_is_bound_before_lease_and_rechecked_around_each_runner_call(native_grant, monkeypatch):
    from apps.api.app.application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
    from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
    v = native_grant
    inputs = live_inputs(v, monkeypatch)
    authority = HttpFixtureCommandAuthority(invocation_id="original-command", request_digest=acceptance_digest("original-input"))
    calls, journals, runner_calls = [], [], []
    cancelled = False
    def bind(original, selected, *, require_current):
        assert original is inputs and selected == authority
        require_current()
        calls.append("bind")
    def require(original, selected):
        assert original is inputs and selected == authority
        if cancelled: raise HttpFixtureInvalid("command cancelled")
        calls.append("require")
    fence = object()
    commands = SimpleNamespace(bind=bind, require=require, fence=lambda *args: fence)
    class Journal:
        def __init__(self, access, artifacts, **options):
            self.access, self.artifacts = access, artifacts
            journals.append(options)
    class Repository:
        def __init__(self, journal): self.journal = journal
        def acquire(self, scope, operation, owner_id, *, require_current):
            assert calls[0] == "bind"
            require_current()
            calls.append("acquire")
            return HttpFixtureWorkLease(scope, operation, owner_id, 1, fixture_work_digest(scope, operation))
        def fence(self, lease): return lease
    def execute(command, **options):
        options["require_work"]()
        runner_calls.append(command)
        return "original-output"
    monkeypatch.setattr(runtime, "PostgresHttpFixtureDispatchJournal", Journal)
    monkeypatch.setattr(runtime, "PostgresHttpFixtureWorkRepository", Repository)
    assembled = factory(v, runner=SimpleNamespace(execute_owned_http=execute), commands=commands).create(inputs,
        owner_id="original-worker", require_current=lambda: None, command_authority=authority)
    assert journals[1]["command_fence"] is fence
    assert calls.index("bind") < calls.index("acquire") and calls.count("require") >= 2
    options = dict(require_work=lambda: None)
    assert assembled.lifecycle.runner.execute_owned_http("one", **options) == "original-output"
    cancelled = True
    with pytest.raises(HttpFixtureInvalid, match="cancelled"):
        assembled.lifecycle.runner.execute_owned_http("two", **options)
    assert runner_calls == ["one"]


@pytest.mark.parametrize("denied", [False, True])
def test_runtime_current_locates_permission_failure_without_changing_original_guards(
        native_grant, monkeypatch, caplog, denied):
    v = native_grant
    inputs = live_inputs(v, monkeypatch)
    calls = []
    error = PermissionError("private://original?api_key=never-log-this")
    name = "apps.api.app.application.quality_loop.http_fixture_diagnostics"
    caplog.set_level(logging.INFO, logger=name)

    def source(scope):
        assert scope is inputs.access_scope
        calls.append("source")

    def grant(project_id, grant_id, **kwargs):
        assert (project_id, grant_id) == (inputs.scope.project_id, inputs.consent.grant_id)
        assert kwargs == {"actor_id": inputs.consent.actor_id, "scope": inputs.scope,
            "operation": inputs.selection.operation, "source_scope_digest": inputs.consent.source_scope_digest}
        calls.append("grant")
        if denied:
            raise error
        return {"grant_digest": inputs.selection.grant_digest}

    monkeypatch.setattr(v.service.authorization, "require_current", source)
    monkeypatch.setattr(v.service.repository, "require_live", grant)
    current = factory(v)._current(inputs, lambda: calls.append("callback"), live=True)
    if denied:
        with pytest.raises(PermissionError) as raised:
            current()
        assert raised.value is error and calls == ["callback", "source", "grant"]
    else:
        current()
        assert calls == ["callback", "source", "grant", "source", "callback"]
    diagnostics = [record for record in caplog.records if record.name == name]
    assert len(diagnostics) == 1 and diagnostics[0].args[0] == "grant_live_permission"
    assert diagnostics[0].exc_info is None and str(error) not in caplog.text
    assert diagnostics[0].levelno == (logging.WARNING if denied else logging.INFO)
    if denied:
        assert diagnostics[0].args[1] == "PermissionError"
    calls.clear()
    caplog.clear()
    factory(v)._current(inputs, lambda: calls.append("callback"), live=False)()
    assert calls == ["callback", "source", "source", "callback"]
    assert not [record for record in caplog.records if record.name == name]
