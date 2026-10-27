"""Read-only protocol specimens, not proof of actual dependency health or coverage."""
from copy import deepcopy
import subprocess
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plan_environment_health import RunPlanEnvironmentHealthApplicationService
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.domain.quality_loop.native_environment_health import NativeEnvironmentHealthObservation
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner.native_maven_build import NativeBuildFailure
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector, POSTGRES_SELECT_ONE
from apps.api.tests.test_owned_target_environment import ARTIFACT, Commands, spec
from apps.api.tests.test_run_plan_environments import state


class HealthCommands(Commands):
    def __init__(self, spec):
        super().__init__(spec)
        self.responses = {"pg": b"1\n", "redis": b"PONG\n", "target": b'{"status":"UP"}\n200'}
        self.health_calls, self.change, self.fail = [], None, None

    def __call__(self, args, **options):
        if args[1:3] != ["exec", "--user"]:
            return super().__call__(args, **options)
        assert options["timeout"] == 10 and options["max_bytes"] == 16384
        options["require_work"]()
        ident = args[4]
        role = "target" if ident == self.spec.container_id else next(item.role for item in self.spec.dependencies if item.container_id == ident)
        user = "65534:65534" if role == "target" else next(item.user for item in self.spec.dependencies if item.role == role)
        assert args[3] == user
        self.calls.append((args, options))
        self.health_calls.append(role)
        if role == self.fail:
            raise NativeBuildFailure("native_build_timeout", b"private output must not escape")
        if self.change:
            self.change(role, self)
        return 0, self.responses[role]


def observe(spec, commands=None, current=lambda: None):
    return OwnedTargetHealthInspector(spec, command=commands or HealthCommands(spec)).inspect(ARTIFACT, require_work=current)


def test_three_exact_read_only_probes_keep_original_inventory_authority_false(spec):
    commands = HealthCommands(spec)
    value = observe(spec, commands)
    assert value.dependency_health_verified and value.target_health_verified
    assert value.inventory["dependency_health_verified"] is False
    assert value.inventory["execution_authorized"] is value.inventory["business_coverage_verified"] is False
    assert commands.health_calls == ["pg", "redis", "target"] and len(commands.calls) == 21
    actual = [args for args, _ in commands.calls if args[1:3] == ["exec", "--user"]]
    assert actual[0][-3:] == ["sh", "-c", POSTGRES_SELECT_ONE]
    assert actual[1][5:] == ["redis-cli", "--raw", "-h", "127.0.0.1", "-p", "6379", "PING"]
    assert actual[2][-1] == "http://127.0.0.1:8080/actuator/health"
    assert "--location" not in actual[2] and "--retry" not in actual[2]
    assert "--disable" in actual[2] and "--noproxy" in actual[2] and "--max-filesize" in actual[2]
    assert "SELECT 1" in POSTGRES_SELECT_ONE and "--no-psqlrc" in POSTGRES_SELECT_ONE
    assert "PGHOSTADDR=127.0.0.1" in POSTGRES_SELECT_ONE and "*[!A-Za-z0-9_]*" in POSTGRES_SELECT_ONE
    assert "POSTGRES_PASSWORD" not in str(value.payload())


@pytest.mark.parametrize("role,response,dependencies,target", [
    ("pg", b"0\n", False, True), ("redis", b"ERR authentication required\n", False, True),
    ("target", b'{"status":"DOWN"}\n503', True, False),
    ("target", b'{"status":"UP"}\n500', True, False),
    ("target", b'{"status":"UNKNOWN"}\n200', True, False),
])
def test_actual_unhealthy_responses_are_not_relabelled_as_verified(spec, role, response, dependencies, target):
    commands = HealthCommands(spec)
    commands.responses[role] = response
    value = observe(spec, commands)
    assert value.dependency_health_verified is dependencies and value.target_health_verified is target


@pytest.mark.parametrize("response", [b'{"status":"DOWN","status":"UP"}\n200', b'{"status":"UP"}',
    b'{"status":"UP"}\n200garbage', b'[]\n200', b'\xff\n200', b'{"value":NaN}\n200'])
def test_malformed_duplicate_or_partial_health_response_rejects_whole_observation(spec, response):
    commands = HealthCommands(spec)
    commands.responses["target"] = response
    with pytest.raises(NativeEnvironmentInvalid): observe(spec, commands)


@pytest.mark.parametrize("fault", ["role", "order", "resource", "image", "restart", "hash", "size", "boolean-size", "encoding", "extra", "missing"])
def test_original_complete_response_cohort_and_exact_instances_cannot_be_rebound(spec, fault):
    value = observe(spec)
    checks = deepcopy(list(value.checks))
    if fault == "role": checks[0]["role"] = "other"
    if fault == "order": checks.reverse()
    if fault == "resource": checks[0]["container_id"] = "9" * 64
    if fault == "image": checks[0]["image_id"] = "sha256:" + "9" * 64
    if fault == "restart": checks[0]["started_at"] = "2026-10-11T00:00:00Z"
    if fault == "hash": checks[0]["response_hash"] = byte_digest(b"different")
    if fault == "size": checks[0]["byte_count"] += 1
    if fault == "boolean-size": checks[0]["byte_count"] = True
    if fault == "encoding": checks[0]["response_base64"] += "="
    if fault == "extra": checks[0]["healthy"] = True
    if fault == "missing": checks.pop()
    with pytest.raises(NativeEnvironmentInvalid):
        NativeEnvironmentHealthObservation(value.inventory, value.inventory_hash, tuple(checks), value.observed_at)


@pytest.mark.parametrize("fault", ["jar", "restart", "network"])
def test_change_during_probes_rejects_original_environment_epoch(spec, fault):
    commands = HealthCommands(spec)
    def change(role, state):
        if role != "target": return
        if fault == "jar": state.body = b"f" * 64 + b"  /app/target.jar\n"
        if fault == "restart": state.containers[spec.container_id]["StartedAt"] = "2026-10-11T00:00:00Z"
        if fault == "network": state.network["Internal"] = False
    commands.change = change
    with pytest.raises(NativeEnvironmentInvalid): observe(spec, commands)


@pytest.mark.parametrize("fault", ["revoked", "timeout", "wrong-owner"])
def test_unavailable_or_revoked_work_does_not_probe_later_dependencies(spec, fault):
    commands = HealthCommands(spec)
    revoked = []
    def current():
        if revoked: raise SourceAccessDenied("revoked")
    if fault == "revoked": commands.change = lambda role, state: revoked.append(True)
    if fault == "timeout": commands.fail = "pg"
    if fault == "wrong-owner": commands.containers[spec.container_id]["Labels"] = {}
    with pytest.raises((SourceAccessDenied, NativeEnvironmentInvalid)):
        observe(spec, commands, current)
    assert "redis" not in commands.health_calls and "target" not in commands.health_calls


def health_service(state):
    commands = HealthCommands(state.spec)
    commands.body = state.binding["metadata"]["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    def inspect_health(project, environment, artifact, *, require_work):
        assert (project, environment) == (state.query.project_id, state.spec.environment_id)
        return OwnedTargetHealthInspector(state.spec, command=commands).inspect(artifact, require_work=require_work)
    health = SimpleNamespace(policy_digest=state.environments.policy_digest, inspect_health=inspect_health)
    return RunPlanEnvironmentHealthApplicationService(state.service, health), commands, health


def test_application_uses_exact_current_plan_and_original_build_but_never_grants_execution(state):
    service, commands, _ = health_service(state)
    originals = deepcopy((state.plan, state.binding))
    result = service.inspect(state.query)
    assert result["dependency_health_verified"] and result["target_health_verified"]
    assert result["request"] == state.query.model_dump(mode="json")
    assert result["historical_not_live"] and not result["environment_fully_verified"]
    assert not result["execution_authorized"] and not result["business_coverage_verified"]
    assert result["automated_count"] == result["executed_on_target_count"] == result["passed_count"] == 0
    assert (state.plan, state.binding) == originals and commands.health_calls == ["pg", "redis", "target"]


@pytest.mark.parametrize("fault", ["role", "stale", "parent", "policy", "origin", "late-source", "late-policy", "late-revocation"])
def test_application_checks_roles_original_ancestry_acl_and_policy_before_and_after_native_work(state, fault):
    service, commands, health = health_service(state)
    if fault == "role": state.auth.role = "developer"
    if fault == "stale": state.plan["current_use"]["inputs_current"] = False
    if fault == "parent": state.binding["metadata"]["run_plan_id"] = "other"
    if fault == "policy": health.policy_digest = lambda *args, **kwargs: byte_digest(b"other")
    if fault == "origin": state.plan["artifact"]["plan"]["selection"]["environment"]["base_url"] = "http://developer:8000"
    if fault.startswith("late-"):
        inspect = health.inspect_health
        def changed(*args, **kwargs):
            result = inspect(*args, **kwargs)
            if fault == "late-source": state.plan["current_use"]["inputs_current"] = False
            if fault == "late-policy": health.policy_digest = lambda *args, **kwargs: byte_digest(b"other")
            if fault == "late-revocation": state.auth.revoked = True
            return result
        health.inspect_health = changed
    with pytest.raises((SourceAccessDenied, RunPlanChanged, RunPlanIntegrityError, NativeEnvironmentInvalid)):
        service.inspect(state.query)
    if not fault.startswith("late-"):
        assert not commands.calls


@pytest.mark.parametrize("field,value", [("POSTGRES_DB", "postgresql://external:5432/database"),
    ("POSTGRES_DB", "database host=external"), ("POSTGRES_DB", ""),
    ("POSTGRES_USER", "reviewer; touch /tmp/forbidden"), ("POSTGRES_USER", "")])
def test_pg_connection_identifiers_cannot_turn_fixed_sql_into_an_external_connection(field, value):
    environment = {"PATH": "/usr/bin:/bin", "POSTGRES_USER": "owned_user", "POSTGRES_DB": "owned_database",
        "POSTGRES_PASSWORD": "private-test-value", field: value}
    result = subprocess.run(["/bin/sh", "-c", POSTGRES_SELECT_ONE], env=environment, capture_output=True, timeout=2)
    assert result.returncode == 2 and result.stdout == result.stderr == b""


@pytest.mark.parametrize("fault", ["untyped", "other-project", "other-environment", "other-policy", "other-jar"])
def test_application_revalidates_the_typed_observation_from_the_port(state, fault):
    service, commands, health = health_service(state)
    original = health.inspect_health
    def forged(*args, **kwargs):
        value = original(*args, **kwargs)
        if fault == "untyped": return value.payload()
        key = {"other-project": "project_id", "other-environment": "environment_id",
            "other-policy": "operator_policy_digest", "other-jar": "artifact_hash"}[fault]
        value.inventory[key] = byte_digest(b"other") if key.endswith("digest") or key.endswith("hash") else "other"
        from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
        return replace_observation_inventory(value, acceptance_digest(value.inventory))
    def replace_observation_inventory(value, inventory_hash):
        return NativeEnvironmentHealthObservation(value.inventory, inventory_hash, value.checks, value.observed_at)
    health.inspect_health = forged
    with pytest.raises(RunPlanIntegrityError): service.inspect(state.query)
