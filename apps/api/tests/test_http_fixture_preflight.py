"""Explicit parent/Docker protocol specimens, not native execution or PG evidence."""
from copy import deepcopy
from dataclasses import replace
import logging
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.execution_work_guard import ExecutionWorkGuard
from apps.api.app.application.quality_loop.http_fixture_journal_access import NativeSavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixtureOutcomeUnknown, HttpFixtureScope
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkLost
from apps.api.app.application.quality_loop.run_plan_environment_health import RunPlanEnvironmentHealthApplicationService
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as journal_module
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.tests.test_http_fixture_native_grants import native_grant
from apps.api.tests.test_http_fixtures import Journal, Runner
from apps.api.tests.test_owned_target_environment import spec
from apps.api.tests.test_owned_target_health import HealthCommands


@pytest.fixture
def preflight(native_grant):
    v = native_grant
    grant = v.service.issue(v.request, invocation_id="preflight-consent")
    scope = HttpFixtureScope(**grant["scope"])
    parent = RunPlanObservationArchiveParent(project_id=scope.project_id, run_plan_id=v.saved["metadata"]["run_plan_id"],
        run_plan_artifact_hash=v.saved["metadata"]["artifact_hash"], plan_digest=scope.parent_digest)
    owned = v.commands.spec
    commands = HealthCommands(owned)
    commands.body = scope.artifact_hash[7:].encode() + b"  /app/target.jar\n"
    original = SimpleNamespace(_access=lambda _: v.service.authorization.scope(scope.project_id),
        authorization=v.service.authorization,
        original_inputs=lambda *_args, **_kwargs: pytest.fail("the fixture already verifies both original parents"))

    def inspect_health(project, environment, artifact, *, require_work):
        assert (project, environment, artifact) == (scope.project_id, scope.environment_id, scope.artifact_hash)
        return OwnedTargetHealthInspector(owned, command=commands).inspect(artifact, require_work=require_work)

    health = SimpleNamespace(policy_digest=lambda *args, **kwargs: owned.digest, inspect_health=inspect_health)
    service = RunPlanEnvironmentHealthApplicationService(original, health)
    access = NativeSavedRunPlanHttpFixtureAccess(v.plans, parent, v.manifest, v.records, grant["native_environment"],
        environment_health=service)
    return SimpleNamespace(v=v, scope=scope, access=access, commands=commands, health=health, service=service,
        command=access.command(scope, "setup"))


def _preflight_messages(caplog):
    return [message for message in caplog.messages if "phase=journal_preflight_" in message]


def test_live_preflight_reads_all_owned_health_responses_without_rewriting_originals(preflight, caplog):
    v = preflight
    originals = deepcopy((v.v.saved, v.v.environment, v.v.manifest, v.v.state["issued"]))
    callbacks = []
    with caplog.at_level(logging.INFO, logger="apps.api.app.application.quality_loop.http_fixture_diagnostics"):
        assert v.access.require_dispatch(v.scope, "setup", v.command, require_work=lambda: callbacks.append(True)) is None
    assert [message.split("phase=")[1].split()[0] for message in _preflight_messages(caplog)] == [
        "journal_preflight_parent_before", "journal_preflight_live_health", "journal_preflight_parent_after",
    ]
    assert v.commands.health_calls == ["pg", "redis", "target"] and len(v.commands.calls) == 13
    assert len(callbacks) > 20
    assert (v.v.saved, v.v.environment, v.v.manifest, v.v.state["issued"]) == originals
    for args, _ in v.commands.calls:
        assert not any(value in args for value in ("POST", "DELETE", "--execute-owned-target-http"))


@pytest.mark.parametrize("phase", ["setup", "cleanup:session"])
def test_journal_preflight_verifies_exact_command_and_reads_one_parent_on_each_side(preflight, monkeypatch, phase):
    v = preflight
    monkeypatch.setattr(journal_module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    journal = PostgresHttpFixtureDispatchJournal(v.access, None, actor_id="admin")
    receipt = {"bindings": [{"binding_id": "session", "value": "original-resource"}]}
    command = v.access.command(v.scope, phase, setup_receipt=receipt)
    if phase != "setup":
        def original(scope, original_phase, **_kwargs):
            assert scope == v.scope and original_phase == "setup"
            return SimpleNamespace(command=v.command, execution=object())
        monkeypatch.setattr(journal, "inspect", original)
        monkeypatch.setattr(journal.verifier, "verify", lambda *_a, **_kw: receipt)
    events = []
    plan_read = v.v.plans.read
    probe = v.service.probe_pinned_inventory

    def paired(project, ident):
        events.append("parent")
        return v.v.records.read(project, ident), plan_read(project, v.access.parent.run_plan_id)

    def health(*args, **kwargs):
        events.append("health")
        return probe(*args, **kwargs)

    def transaction():
        events.append("transaction")
        raise RuntimeError("stop before write transaction")

    monkeypatch.setattr(v.v.records, "read_with_plan", paired, raising=False)
    monkeypatch.setattr(v.service, "probe_pinned_inventory", health)
    monkeypatch.setattr(journal_module, "session_scope", transaction)
    with pytest.raises(HttpFixtureInvalid):
        journal.claim(v.scope, phase, replace(command, steps=()), require_current=lambda: None)
    assert "health" not in events and "transaction" not in events
    events.clear()
    with pytest.raises(RuntimeError, match="stop before write transaction"):
        journal.claim(v.scope, phase, command, require_current=lambda: None)
    assert events == ["parent", "health", "parent", "transaction"]
    assert v.commands.health_calls == ["pg", "redis", "target"]


@pytest.mark.parametrize("paired", [False, True])
def test_preflight_uses_each_verified_environment_once_and_rechecks_after_probes(preflight, monkeypatch, paired):
    v = preflight
    events = []
    read_environment = v.v.records.read
    read_plan = v.v.plans.read

    def environment(project, ident):
        events.append("environment")
        return read_environment(project, ident)

    def plan(project, ident):
        events.append("plan")
        return read_plan(project, ident)

    def pair(project, ident):
        return environment(project, ident), plan(project, v.access.parent.run_plan_id)

    inspect = v.service.probe_pinned_inventory

    def health(*args, **kwargs):
        events.append("health")
        return inspect(*args, **kwargs)

    monkeypatch.setattr(v.v.records, "read", environment)
    monkeypatch.setattr(v.v.plans, "read", plan)
    if paired:
        monkeypatch.setattr(v.v.records, "read_with_plan", pair, raising=False)
    monkeypatch.setattr(v.service, "probe_pinned_inventory", health)
    v.access.require_dispatch(v.scope, "setup", v.command, require_work=lambda: None)
    per_scope = ["environment", "plan"] if paired else ["plan", "environment"]
    assert events == per_scope + ["health"] + per_scope
    assert v.commands.health_calls == ["pg", "redis", "target"]


@pytest.mark.parametrize("fault", ["none", "lease-loss", "review-withdrawal"])
def test_probes_poll_live_fence_and_full_verification_rejects_late_changes(preflight, fault):
    v = preflight
    calls = []

    def full():
        pytest.fail("preflight verifies its own full parents; the worker should only check live ownership")

    def poll():
        calls.append("poll")
        if fault == "lease-loss" and "pg" in v.commands.health_calls:
            raise HttpFixtureWorkLost("lost during the original probe")

    def changed(role, _state):
        calls.append(role)
        if role == "target" and fault == "review-withdrawal":
            v.v.saved["current_use"]["inputs_current"] = False

    v.commands.change = changed
    guard = ExecutionWorkGuard(full, poll)
    if fault == "none":
        assert v.access.require_dispatch(v.scope, "setup", v.command, require_work=guard) is None
        assert calls[-1] == "poll"
    else:
        error = HttpFixtureWorkLost if fault == "lease-loss" else RunPlanChanged
        with pytest.raises(error):
            v.access.require_dispatch(v.scope, "setup", v.command, require_work=guard)
    assert v.commands.health_calls == (["pg"] if fault == "lease-loss" else ["pg", "redis", "target"])
    assert "poll" in calls


def test_in_transaction_dispatch_scope_requires_current_review(preflight):
    v = preflight
    assert v.access.require_dispatch_scope(v.scope) == v.access.parent.model_dump(mode="json")
    v.v.saved["current_use"]["inputs_current"] = False
    with pytest.raises(RunPlanChanged):
        v.access.require_dispatch_scope(v.scope)
    assert v.access.require_scope(v.scope) == v.access.parent.model_dump(mode="json")
    assert not v.commands.calls


def test_historical_access_does_not_require_a_live_target_or_repeat_probes(preflight):
    v = preflight
    v.access.environment_health = None
    assert v.access.require_scope(v.scope) == v.access.parent.model_dump(mode="json")
    assert v.access.command(v.scope, "setup") == v.command
    assert not v.commands.calls
    with pytest.raises(HttpFixtureInvalid, match="live target health port"):
        v.access.require_dispatch(v.scope, "setup", v.command, require_work=lambda: None)
    assert not v.commands.calls


@pytest.mark.parametrize("role,body", [("pg", b"0\n"), ("redis", b"ERR\n"),
    ("target", b'{"status":"DOWN"}\n503'), ("target", b'{"status":"UP"}\n500')])
def test_unhealthy_original_response_rejects_dispatch_without_changing_the_inventory(preflight, role, body, caplog):
    v = preflight
    original = deepcopy(v.v.environment)
    v.commands.responses[role] = body
    with caplog.at_level(logging.WARNING, logger="apps.api.app.application.quality_loop.http_fixture_diagnostics"), \
            pytest.raises(NativeEnvironmentInvalid, match="epoch or dependency health"):
        v.access.require_dispatch(v.scope, "setup", v.command, require_work=lambda: None)
    assert v.v.environment == original
    messages = _preflight_messages(caplog)
    assert len(messages) == 1
    assert messages[0].startswith("Fixture lifecycle phase failed; phase=journal_preflight_live_health "
                                  "failure_type=NativeEnvironmentInvalid elapsed_ms=")
    assert messages[0].rsplit("=", 1)[-1].isdigit()


@pytest.mark.parametrize("fault", ["restart", "policy", "artifact", "stopped", "developer-network", "bad-health", "stale", "revoked"])
def test_target_scope_and_current_original_inputs_fail_closed_before_dispatch(preflight, fault):
    v = preflight
    if fault == "restart": v.commands.containers[v.commands.spec.container_id]["StartedAt"] = "2026-10-12T01:00:00Z"
    elif fault == "policy": v.health.policy_digest = lambda *args, **kwargs: acceptance_digest("other operator")
    elif fault == "artifact": v.commands.body = b"f" * 64 + b"  /app/target.jar\n"
    elif fault == "stopped": v.commands.containers[v.commands.spec.container_id]["Running"] = False
    elif fault == "developer-network": v.commands.network["Internal"] = False
    elif fault == "bad-health": v.commands.responses["target"] = b'{"status":"DOWN","status":"UP"}\n200'
    elif fault == "stale": v.v.saved["current_use"]["inputs_current"] = False
    else: v.v.state["revoked"] = True
    with pytest.raises((NativeEnvironmentInvalid, RunPlanChanged, SourceAccessDenied)):
        v.access.require_dispatch(v.scope, "setup", v.command, require_work=lambda: None)
    if fault in {"policy", "stale", "revoked"}: assert not v.commands.calls


@pytest.mark.parametrize("fault", ["phase", "project", "metadata", "boolean", "timeout", "origin", "untyped"])
def test_dispatch_command_cannot_rebind_original_scope_before_native_probes(preflight, fault):
    v = preflight
    phase, command = "setup", v.command
    if fault == "phase": phase = "cleanup:unknown"
    elif fault == "project": command = replace(command, project_id="foreign-project")
    elif fault == "metadata": command = replace(command, metadata={})
    elif fault == "boolean": command = replace(command, metadata={**command.metadata, "business_coverage_verified": 0})
    elif fault == "timeout": command = replace(command, timeout_ms=1000)
    elif fault == "origin": command = replace(command, base_url="http://localhost:8000")
    else: command = {}
    with pytest.raises(HttpFixtureInvalid):
        v.access.require_dispatch(v.scope, phase, command, require_work=lambda: None)
    assert not v.commands.calls


@pytest.mark.parametrize("role", ["pg", "redis", "target"])
def test_worker_loss_during_health_stops_before_later_probes(preflight, role):
    v = preflight
    lost = []
    v.commands.change = lambda current, state: lost.append(True) if current == role else None
    def current():
        if lost: raise HttpFixtureWorkLost("explicit original worker lost")
    with pytest.raises(HttpFixtureWorkLost):
        v.access.require_dispatch(v.scope, "setup", v.command, require_work=current)
    assert v.commands.health_calls == ["pg", "redis", "target"][:["pg", "redis", "target"].index(role) + 1]


@pytest.mark.parametrize("fault", ["stale", "revoked", "policy", "inventory", "untyped", "record_request"])
def test_late_changes_or_forged_port_output_do_not_release_new_dispatch(preflight, fault):
    v = preflight
    original = v.service.probe_pinned_inventory
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == "stale": v.v.saved["current_use"]["inputs_current"] = False
        elif fault == "revoked": v.v.state["revoked"] = True
        elif fault == "policy": v.v.saved["artifact"]["plan"]["selection"]["environment"]["inventory_hash"] = acceptance_digest("changed")
        elif fault == "inventory": result.inventory["target"]["started_at"] = "2026-10-12T01:00:00Z"
        elif fault == "untyped": result = result.payload()
        else: v.v.environment["archive"]["request"]["build_binding_id"] = "foreign-binding"
        return result
    v.access.environment_health = SimpleNamespace(probe_pinned_inventory=changed)
    with pytest.raises((NativeEnvironmentInvalid, RunPlanChanged, SourceAccessDenied, HttpFixtureInvalid)):
        v.access.require_dispatch(v.scope, "setup", v.command, require_work=lambda: None)
    assert v.commands.health_calls == ["pg", "redis", "target"]


def test_journal_rejects_native_dispatch_before_opening_a_write_transaction(preflight, monkeypatch):
    v = preflight
    monkeypatch.setattr(journal_module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    transactions = []
    def forbidden():
        transactions.append(True)
        raise AssertionError("failed preflight must not open a journal write transaction")
    monkeypatch.setattr(journal_module, "session_scope", forbidden)
    journal = PostgresHttpFixtureDispatchJournal(v.access, None, actor_id="admin")
    for fault in ("missing-port", "unhealthy", "stale"):
        v.access.environment_health = None if fault == "missing-port" else v.service
        v.commands.responses["pg"] = b"0\n" if fault == "unhealthy" else b"1\n"
        v.v.saved["current_use"]["inputs_current"] = fault != "stale"
        with pytest.raises((HttpFixtureInvalid, NativeEnvironmentInvalid, RunPlanChanged)):
            journal.claim(v.scope, "setup", v.command, require_current=lambda: None)
    assert not transactions


def test_cleanup_preflight_keeps_only_the_original_capture_bound_phase(preflight):
    v = preflight
    command = v.access.command(v.scope, "cleanup:session", setup_receipt={"bindings": [
        {"binding_id": "session", "value": "original-resource"}]})
    assert command.steps[0]["path"] == "/sessions/original-resource/close"
    v.access.require_dispatch(v.scope, "cleanup:session", command, require_work=lambda: None)
    assert v.commands.health_calls == ["pg", "redis", "target"]


@pytest.mark.parametrize("unknown", [False, True])
def test_lifecycle_replays_original_results_or_unknown_effect_without_repeating_live_probes(preflight, unknown):
    v = preflight
    class NativeJournal(Journal):
        def claim(self, scope, phase, command, *, require_current):
            v.access.require_dispatch(scope, phase, command, require_work=require_current)
            return super().claim(scope, phase, command, require_current=require_current)
    runner, journal = Runner(), NativeJournal()
    if unknown: runner.failure = TimeoutError("explicit uncertain target effect")
    service = HttpFixtureLifecycleApplicationService(runner, journal, OwnedHttpFixtureObservationVerifier())
    if unknown:
        with pytest.raises(HttpFixtureOutcomeUnknown): service.prepare(v.scope, v.v.manifest, require_work=lambda: None)
    else:
        result = service.prepare(v.scope, v.v.manifest, require_work=lambda: None)
    calls = len(v.commands.calls)
    v.access.environment_health = None
    if unknown:
        with pytest.raises(HttpFixtureOutcomeUnknown): service.prepare(v.scope, v.v.manifest, require_work=lambda: None)
    else:
        assert service.prepare(v.scope, v.v.manifest, require_work=lambda: None) == result
    assert len(v.commands.calls) == calls == 13 and len(runner.commands) == 1
