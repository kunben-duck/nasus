"""Operator registry fixtures contain no database, model or target credentials."""
from dataclasses import asdict
import json
import os

import pytest

from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.infrastructure.runner.configured_target_environments import ConfiguredOwnedTargetEnvironments, REGISTRY_SCHEMA, read_registry
from apps.api.tests.test_owned_target_environment import ARTIFACT, Commands, spec


@pytest.fixture
def registry(tmp_path, monkeypatch, spec):
    path = tmp_path / "operator-registry.json"
    path.write_text(json.dumps({"schema": REGISTRY_SCHEMA, "environments": [asdict(spec)]}))
    path.chmod(0o600)
    monkeypatch.setenv("NASUS_TARGET_ENVIRONMENT_REGISTRY", str(path))
    return path


def test_only_exact_operator_project_and_environment_can_select_owned_resources(registry, spec):
    commands = Commands(spec)
    adapter = ConfiguredOwnedTargetEnvironments(command=commands)
    assert read_registry(str(registry)) == (spec,)
    assert adapter.policy_digest(spec.project_id, spec.environment_id, require_work=lambda: None) == spec.digest
    result = adapter.inspect(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)
    assert result.inventory["operator_policy_digest"] == spec.digest
    for project, environment in (("other", spec.environment_id), (spec.project_id, "other")):
        before = len(commands.calls)
        with pytest.raises(NativeEnvironmentInvalid): adapter.inspect(project, environment, ARTIFACT, require_work=lambda: None)
        assert len(commands.calls) == before


@pytest.mark.parametrize("fault", ["mode", "symlink", "empty", "oversize", "duplicate-key", "nonfinite", "extra-field",
    "credentials", "same-cohort", "mutable-image", "root", "duplicate-role", "invalid-container-type"])
def test_registry_fails_closed_before_any_docker_operation(registry, spec, fault):
    payload = json.loads(registry.read_text())
    if fault == "mode": registry.chmod(0o644)
    elif fault == "symlink":
        target = registry.with_suffix(".target")
        registry.rename(target)
        registry.symlink_to(target)
    elif fault == "empty": registry.write_text("")
    elif fault == "oversize": registry.write_text("x" * (256 * 1024 + 1))
    elif fault == "duplicate-key": registry.write_text('{"schema":"a","schema":"b","environments":[]}')
    elif fault == "nonfinite": registry.write_text('{"schema":"nasus.owned-target-registry.v1","environments":NaN}')
    else:
        if fault == "extra-field": payload["extra"] = "forbidden"
        if fault == "credentials": payload["environments"][0]["api_key"] = "private-key"
        if fault == "same-cohort": payload["environments"].append({**payload["environments"][0], "environment_id": "other"})
        if fault == "mutable-image": payload["environments"][0]["image_id"] = "java:latest"
        if fault == "root": payload["environments"][0]["dependencies"][0]["user"] = "0:0"
        if fault == "duplicate-role": payload["environments"][0]["dependencies"][1]["role"] = "pg"
        if fault == "invalid-container-type": payload["environments"][0]["container_id"] = []
        registry.write_text(json.dumps(payload))
    calls = []
    adapter = ConfiguredOwnedTargetEnvironments(command=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(NativeEnvironmentInvalid) as error:
        adapter.inspect(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)
    assert calls == [] and "private-key" not in str(error.value)


def test_unconfigured_registry_never_discovers_developer_containers(monkeypatch, spec):
    monkeypatch.delenv("NASUS_TARGET_ENVIRONMENT_REGISTRY", raising=False)
    with pytest.raises(NativeEnvironmentInvalid):
        ConfiguredOwnedTargetEnvironments().inspect(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)


def test_operator_registry_change_during_inspection_is_not_accepted(registry, spec):
    commands = Commands(spec)
    def changed(_):
        payload = json.loads(registry.read_text())
        payload["environments"][0]["environment_id"] = "replacement"
        registry.write_text(json.dumps(payload))
    commands.after = changed
    with pytest.raises(NativeEnvironmentInvalid):
        ConfiguredOwnedTargetEnvironments(command=commands).inspect(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)


def test_access_callback_failure_is_not_hidden_by_registry_or_docker(registry, spec):
    calls = []
    def revoked(): raise PermissionError("revoked")
    with pytest.raises(PermissionError, match="revoked"):
        ConfiguredOwnedTargetEnvironments(command=lambda *args, **kwargs: calls.append(args)).inspect(
            spec.project_id, spec.environment_id, ARTIFACT, require_work=revoked)
    assert calls == []


def test_health_port_uses_the_same_exact_private_registry_without_changing_inventory(registry, spec):
    from apps.api.tests.test_owned_target_health import HealthCommands
    commands = HealthCommands(spec)
    adapter = ConfiguredOwnedTargetEnvironments(command=commands)
    value = adapter.inspect_health(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)
    assert value.dependency_health_verified and value.target_health_verified
    assert value.inventory["dependency_health_verified"] is False
    assert read_registry(str(registry)) == (spec,)
    for project, environment in (("other", spec.environment_id), (spec.project_id, "other")):
        before = len(commands.calls)
        with pytest.raises(NativeEnvironmentInvalid):
            adapter.inspect_health(project, environment, ARTIFACT, require_work=lambda: None)
        assert len(commands.calls) == before


def test_health_port_rechecks_registry_after_all_native_probes(registry, spec):
    from apps.api.tests.test_owned_target_health import HealthCommands
    commands = HealthCommands(spec)
    def change(role, state):
        if role == "target":
            payload = json.loads(registry.read_text())
            payload["environments"][0]["image_id"] = "sha256:" + "9" * 64
            registry.write_text(json.dumps(payload))
    commands.change = change
    with pytest.raises(NativeEnvironmentInvalid):
        ConfiguredOwnedTargetEnvironments(command=commands).inspect_health(
            spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)
    assert commands.health_calls == ["pg", "redis", "target"]


def test_missing_registry_and_revoked_health_work_never_discover_developer_instances(monkeypatch, spec):
    calls = []
    adapter = ConfiguredOwnedTargetEnvironments(command=lambda *args, **kwargs: calls.append(args))
    monkeypatch.delenv("NASUS_TARGET_ENVIRONMENT_REGISTRY", raising=False)
    with pytest.raises(NativeEnvironmentInvalid):
        adapter.inspect_health(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)
    def revoked(): raise PermissionError("revoked")
    with pytest.raises(PermissionError, match="revoked"):
        adapter.inspect_health(spec.project_id, spec.environment_id, ARTIFACT, require_work=revoked)
    assert not calls
