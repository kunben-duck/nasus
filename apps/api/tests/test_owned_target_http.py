"""Protocol doubles test admission; real exweb execution is verified separately."""
import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.infrastructure.runner.configured_target_environments import ConfiguredOwnedTargetEnvironments
from apps.api.app.infrastructure.runner.native_maven_build import bounded_command
from apps.api.app.infrastructure.runner.owned_target_http import CLI, ConfiguredOwnedTargetHttpRunner
from apps.api.app.infrastructure.runner.request_wire import runner_request_body
from apps.api.tests.test_configured_target_environments import registry
from apps.api.tests.test_owned_target_environment import ARTIFACT, Commands, spec
from apps.api.tests.test_http_runner_observations import command, payload


@pytest.fixture
def execution(spec, registry):
    value = replace(command(), project_id=spec.project_id, base_url="http://127.0.0.1:8080")
    docker, dispatched = Commands(spec), []
    environments = ConfiguredOwnedTargetEnvironments(command=docker)
    inventory = environments.inspect(spec.project_id, spec.environment_id, ARTIFACT, require_work=lambda: None)

    def child(args, **options):
        assert Path(args[1]) == CLI and args[2] == "--execute-owned-target-http"
        assert CLI.is_file() and args[0] == str(Path(shutil.which("node")).resolve())
        options["require_work"]()
        envelope = json.loads(options["input_body"])
        assert envelope["schema"] == "nasus.owned-http-command.v1"
        assert envelope["inventory"] == inventory.inventory
        assert base64.b64decode(envelope["wire_body_base64"]) == runner_request_body(value)
        assert str(registry) not in args and spec.container_id not in args
        dispatched.append(deepcopy(envelope))
        return 0, json.dumps(payload(value), ensure_ascii=False).encode()

    adapter = ConfiguredOwnedTargetHttpRunner(node_executable=shutil.which("node"), environments=environments, command=child)
    return value, inventory, adapter, dispatched, docker


def execute(execution, spec, *, require_work=lambda: None):
    job, inventory, adapter, *_ = execution
    return adapter.execute_owned_http(job, environment_id=spec.environment_id, artifact_hash=ARTIFACT,
        inventory_hash=inventory.inventory_hash, require_work=require_work)


def test_owned_port_preserves_original_wire_result_and_full_namespace_pin(execution, spec):
    job, inventory, _, dispatched, _ = execution
    outcome = execute(execution, spec)
    assert outcome.request_body == runner_request_body(job)
    assert json.loads(outcome.result_body) == payload(job)
    assert outcome.result.status == "passed" and outcome.result.runner_mode == "http_native"
    assert outcome.inventory_hash == inventory.inventory_hash and outcome.environment_id == spec.environment_id
    assert outcome.result.execution_receipt["target_build_verified"] is False
    assert outcome.result.execution_receipt["business_coverage_verified"] is False
    assert inventory.inventory["execution_authorized"] is False and len(dispatched) == 1


@pytest.mark.parametrize("fault", ["project", "environment", "inventory", "artifact", "kind", "origin", "timeout", "boolean-timeout", "oversize"])
def test_invalid_original_scope_never_starts_owned_http(execution, spec, fault):
    job, inventory, adapter, dispatched, _ = execution
    fields = dict(environment_id=spec.environment_id, artifact_hash=ARTIFACT, inventory_hash=inventory.inventory_hash)
    if fault == "project": job = replace(job, project_id="foreign")
    if fault == "environment": fields["environment_id"] = "foreign"
    if fault == "inventory": fields["inventory_hash"] = "sha256:" + "0" * 64
    if fault == "artifact": fields["artifact_hash"] = "sha256:" + "0" * 64
    if fault == "kind": job = replace(job, kind="browser")
    if fault == "origin": job = replace(job, base_url="http://127.0.0.1:8000")
    if fault == "timeout": job = replace(job, timeout_ms=120001)
    if fault == "boolean-timeout": job = replace(job, timeout_ms=True)
    if fault == "oversize": job = replace(job, metadata={"oversize": "x" * (512 * 1024)})
    with pytest.raises(NativeEnvironmentInvalid):
        adapter.execute_owned_http(job, **fields, require_work=lambda: None)
    assert not dispatched


@pytest.mark.parametrize("fault", ["job", "request-hash", "response-bytes", "false-pass", "duplicate-key", "nonfinite", "exit-code", "oversize", "no-receipt"])
def test_unverified_child_result_is_never_promoted(execution, spec, fault):
    job, _, adapter, _, _ = execution
    result = payload(job)
    if fault == "job": result["runner_job_id"] = "other"
    if fault == "request-hash": result["execution_receipt"]["request_hash"] = "sha256:" + "0" * 64
    if fault == "response-bytes": result["artifacts"][0]["content_base64"] = base64.b64encode(b"changed").decode()
    if fault == "false-pass": result["execution_receipt"]["passed_assertion_count"] = 0
    if fault == "no-receipt": result.pop("execution_receipt")
    body = json.dumps(result).encode()
    if fault == "duplicate-key": body = b'{"status":"passed","status":"error"}'
    if fault == "nonfinite": body = b'{"status":NaN}'
    if fault == "oversize": body = b"x" * (24 * 1024 * 1024 + 1)
    adapter.command = lambda *args, **options: (2 if fault == "exit-code" else 0, body)
    with pytest.raises(NativeEnvironmentInvalid): execute(execution, spec)


@pytest.mark.parametrize("role", ["app", "pg", "redis"])
def test_restarted_original_instance_cannot_return_a_verified_outcome(execution, spec, role):
    _, _, adapter, _, docker = execution
    original = adapter.command
    def changed(*args, **options):
        response = original(*args, **options)
        ident = spec.container_id if role == "app" else next(item.container_id for item in spec.dependencies if item.role == role)
        docker.containers[ident]["StartedAt"] = "2026-10-11T01:00:00Z"
        return response
    adapter.command = changed
    with pytest.raises(NativeEnvironmentInvalid): execute(execution, spec)


def test_registry_changes_are_checked_while_the_child_is_running(execution, spec, registry):
    _, _, adapter, dispatched, _ = execution
    def changed(*args, **options):
        registry.write_text('{"schema":"changed","environments":[]}')
        options["require_work"]()
        pytest.fail("revoked registry continued dispatch")
    adapter.command = changed
    with pytest.raises(NativeEnvironmentInvalid): execute(execution, spec)
    assert not dispatched


def test_authorization_revocation_is_not_hidden_by_result_validation(execution, spec):
    _, _, adapter, dispatched, _ = execution
    revoked = False
    def current():
        if revoked: raise PermissionError("revoked")
    def child(*args, **options):
        nonlocal revoked
        revoked = True
        options["require_work"]()
    adapter.command = child
    with pytest.raises(PermissionError, match="revoked"): execute(execution, spec, require_work=current)
    assert not dispatched


def test_failed_original_oracle_stays_failed_in_the_owned_port(execution, spec):
    job, _, adapter, _, _ = execution
    result = payload(job, body=b'{"message":"HTTP fixture","nested":{"a/b":{"~name":[2]}}}',
        states=["passed", "passed", "failed", "not_executed", "not_executed"], status="failed")
    adapter.command = lambda *args, **options: (0, json.dumps(result).encode())
    assert execute(execution, spec).result.status == "failed"


def test_bounded_subprocess_preserves_binary_stdin_without_pipe_deadlock():
    body = b"\x00" + b"x" * (512 * 1024) + b"\xff"
    code, actual = bounded_command([sys.executable, "-c", "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"],
        timeout=3, max_bytes=1024 * 1024, input_body=body)
    assert code == 0 and actual == body


@pytest.mark.parametrize("body", ["not-bytes", b"x" * (1024 * 1024 + 1)])
def test_invalid_stdin_is_rejected_before_child_creation(body, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError):
        bounded_command([sys.executable], timeout=3, max_bytes=1024, input_body=body)
    assert not calls
