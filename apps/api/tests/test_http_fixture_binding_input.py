"""Cross-language native protocol and physical specimens, not target/PG/exweb gold."""
import base64
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand, FixtureBoundHttpCommand
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA, http_binding_value_hash
from apps.api.app.domain.quality_loop.http_fixture_binding_input import build_fixture_input
from apps.api.app.domain.quality_loop.runner_observations import RunnerObservationInvalid
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
from apps.api.app.infrastructure.runner.request_wire import runner_request_body, runner_request_hash
from apps.api.app.infrastructure.runner.owned_target_http import ConfiguredOwnedTargetHttpRunner
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec


PROBE = Path(__file__).with_name("http_fixture_binding_probe.mjs")


@pytest.fixture
def bound_command(case_inputs):
    v = case_inputs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    capsule, phase = prepared.fixture_captures[0], v.state["phases"][0][1]
    source = phase.execution
    value = build_fixture_input(capsule, source.request_body, source.result_body)
    binding = capsule.captures[0].binding_id
    command = FixtureBoundHttpCommand(job_id="native-fixture-business-specimen", project_id=capsule.project_id,
        us_id=capsule.case_id, base_url="http://127.0.0.1:8080", timeout_ms=5000,
        metadata={"case_id": capsule.case_id, "plan_digest": capsule.plan_digest,
            "fixture_scope_digest": capsule.scope_digest, "fixture_capture_digest": capsule.digest},
        fixture_input=value, steps=({"action": "use_fixture_binding", "binding_id": binding, "source_step_indices": [0]},
            {"action": "request", "request_id": "business", "method": "GET", "path": "/sessions/{{" + binding + "}}",
                "headers_json": "{}", "body_json": "null", "source_step_indices": [0]},
            {"action": "assert_json", "request_id": "business", "pointer": "/status", "value_json": '"ACTIVE"', "source_step_indices": [0]}))
    return command, capsule


def probe(body):
    node = shutil.which("node")
    assert node, "Node is required for the native v3 protocol contract"
    result = subprocess.run([node, str(PROBE)], input=body, capture_output=True, timeout=15, check=True)
    assert result.stderr == b""
    return json.loads(result.stdout)


def unchecked_wire(command):
    """Only malicious protocol specimens bypass the trusted serializer in tests."""
    return json.dumps({"job_id": command.job_id, "project_id": command.project_id, "us_id": command.us_id,
        "base_url": command.base_url, "steps": list(command.steps), "timeout_ms": command.timeout_ms,
        "metadata": command.metadata, "receipt_protocol": command.http_protocol, "execution_kind": command.kind,
        "fixture_input": command.fixture_input}, ensure_ascii=False, separators=(",", ":")).encode()


def test_original_setup_capsule_is_consumed_by_node_and_physically_reverified_by_python(bound_command):
    command, capsule = bound_command
    original = deepcopy(asdict(command))
    wire = runner_request_body(command)
    native = probe(wire)
    assert native["accepted"] is True and native["result"]["status"] == "passed"
    assert native["visits"] == [{"method": "GET", "path": "/sessions/" + capsule.captures[0].value}]
    result = HttpAutomationRunner._result_from_payload(command, native["result"], request_hash=byte_digest(wire))
    receipt = HTTPRunnerObservationVerifier().verify(command, result)
    assert receipt["schema"] == HTTP_FIXTURE_RECEIPT_SCHEMA
    assert receipt["fixture_input_hash"] == acceptance_digest(command.fixture_input)
    assert receipt["fixture_capture_digest"] == capsule.digest
    assert receipt["fixture_bindings"][0]["value_hash"] == capsule.captures[0].value_hash
    assert receipt["steps"][0]["kind"] == "action" and receipt["assertion_count"] == 1
    assert receipt["requests"][0]["input_hash"] != receipt["requests"][0]["declared_input_hash"]
    assert receipt["target_build_verified"] is receipt["business_coverage_verified"] is False
    assert asdict(command) == original and "fixture_input=" not in repr(command)


@pytest.mark.parametrize("fault", ["wrong_case", "wrong_plan", "extra_flag", "missing_source", "capture_value",
    "capture_pointer", "source_bytes", "wrong_origin", "unknown_import", "partial_path", "query", "forward", "duplicate", "oracle_operand"])
def test_python_and_node_reject_rebinding_before_any_business_transport(bound_command, fault):
    command, _capsule = bound_command
    command = deepcopy(command)
    value, steps = command.fixture_input, list(command.steps)
    if fault == "wrong_case": command = replace(command, us_id="another-case")
    elif fault == "wrong_plan":
        value["capture_set"]["plan_digest"] = acceptance_digest("another plan")
        command.metadata["plan_digest"] = value["capture_set"]["plan_digest"]
    elif fault == "extra_flag": value["verified"] = True
    elif fault == "missing_source": value.pop("source_result_body_base64")
    elif fault == "capture_value":
        value["capture_set"]["captures"][0]["value"] = "another_resource"
        value["capture_set"]["captures"][0]["value_hash"] = http_binding_value_hash("another_resource")
    elif fault == "capture_pointer": value["capture_set"]["captures"][0]["pointer"] = "/another_field"
    elif fault == "source_bytes": value["source_result_body_base64"] += "\n"
    elif fault == "wrong_origin": command = replace(command, base_url="http://127.0.0.1:9091")
    elif fault == "unknown_import": steps[0]["binding_id"] = "another_binding"
    elif fault == "partial_path": steps[1]["path"] = "/sessions/prefix{{session}}"
    elif fault == "query": steps[1]["path"] = "/sessions?id={{session}}"
    elif fault == "forward": steps[0], steps[1] = steps[1], steps[0]
    elif fault == "duplicate": steps.insert(0, deepcopy(steps[0]))
    elif fault == "oracle_operand": steps[0]["value_json"] = '"ACTIVE"'
    value["capture_set_digest"] = acceptance_digest(value["capture_set"])
    command.metadata["fixture_capture_digest"] = value["capture_set_digest"]
    command = replace(command, steps=tuple(steps))
    with pytest.raises(ValueError): runner_request_body(command)
    assert probe(unchecked_wire(command)) == {"accepted": False, "visits": []}


def test_self_consistent_rehashed_capture_and_source_receipt_are_rejected_against_physical_bytes(bound_command):
    command, _capsule = bound_command
    command = deepcopy(command)
    value = command.fixture_input
    output = json.loads(base64.b64decode(value["source_result_body_base64"]))
    capture = output["execution_receipt"]["bindings"][0]
    capture.update(value="self_consistent_fake", value_hash=http_binding_value_hash("self_consistent_fake"))
    output["artifacts"][-1]["content_base64"] = base64.b64encode(json.dumps(output["execution_receipt"]).encode()).decode()
    raw = json.dumps(output).encode()
    value["source_result_body_base64"] = base64.b64encode(raw).decode()
    value["capture_set"]["setup_result_hash"] = byte_digest(raw)
    value["capture_set"]["captures"] = deepcopy(output["execution_receipt"]["bindings"])
    value["capture_set_digest"] = acceptance_digest(value["capture_set"])
    command.metadata["fixture_capture_digest"] = value["capture_set_digest"]
    with pytest.raises(RunnerObservationInvalid): runner_request_body(command)
    assert probe(unchecked_wire(command)) == {"accepted": False, "visits": []}


def test_rehashed_success_cannot_hide_a_source_oracle_contradicted_by_its_actual_response(bound_command):
    command, _capsule = bound_command
    command = deepcopy(command)
    value = command.fixture_input
    source = json.loads(base64.b64decode(value["source_request_body_base64"]))
    next(step for step in source["steps"] if step["action"] == "assert_status")["value"] = "404"
    request = json.dumps(source).encode()
    output = json.loads(base64.b64decode(value["source_result_body_base64"]))
    output["execution_receipt"]["request_hash"] = byte_digest(request)
    output["artifacts"][-1]["content_base64"] = base64.b64encode(json.dumps(output["execution_receipt"]).encode()).decode()
    result = json.dumps(output).encode()
    value.update(source_request_body_base64=base64.b64encode(request).decode(), source_result_body_base64=base64.b64encode(result).decode())
    value["capture_set"].update(setup_request_hash=byte_digest(request), setup_result_hash=byte_digest(result))
    value["capture_set_digest"] = acceptance_digest(value["capture_set"])
    command.metadata["fixture_capture_digest"] = value["capture_set_digest"]
    with pytest.raises(RunnerObservationInvalid): runner_request_body(command)
    assert probe(unchecked_wire(command)) == {"accepted": False, "visits": []}


@pytest.mark.parametrize("field", ["fixture_input_hash", "fixture_capture_digest", "fixture_bindings"])
def test_native_result_cannot_drop_or_rebind_its_original_import_receipt(bound_command, field):
    command, _capsule = bound_command
    raw = probe(runner_request_body(command))["result"]
    receipt = raw["execution_receipt"]
    receipt[field] = [] if field == "fixture_bindings" else acceptance_digest("wrong original input")
    raw["artifacts"][-1]["content_base64"] = base64.b64encode(json.dumps(receipt).encode()).decode()
    with pytest.raises(RunnerObservationInvalid):
        HttpAutomationRunner._result_from_payload(command, raw, request_hash=runner_request_hash(command))


def test_legacy_command_archive_shape_does_not_gain_a_null_fixture_field():
    command = AutomationRunnerCommand("legacy-job", "project", "case", "http://127.0.0.1:8080", (), 1000)
    assert "fixture_input" not in asdict(command) and "fixture_input" not in json.loads(runner_request_body(command))


@pytest.mark.parametrize("fault", ["environment", "artifact", "inventory", "policy"])
def test_owned_worker_rejects_a_different_live_target_epoch_before_cli_dispatch(bound_command, fault):
    command, capsule = bound_command
    calls = []
    class Environments:
        def inspect(self, *args, **kwargs):
            kwargs["require_work"]()
            return SimpleNamespace(inventory_hash=capsule.inventory_hash, inventory={"operator_policy_digest":
                acceptance_digest("different policy") if fault == "policy" else capsule.operator_policy_digest})
    def unexpected(*args, **kwargs):
        calls.append(args)
        raise AssertionError("target CLI must not dispatch for a rebound fixture epoch")
    runner = ConfiguredOwnedTargetHttpRunner(node_executable=shutil.which("node"), environments=Environments(), command=unexpected)
    with pytest.raises(NativeEnvironmentInvalid):
        runner.execute_owned_http(command,
            environment_id="another-environment" if fault == "environment" else capsule.environment_id,
            artifact_hash=acceptance_digest("another artifact") if fault == "artifact" else capsule.target_artifact_hash,
            inventory_hash=acceptance_digest("another inventory") if fault == "inventory" else capsule.inventory_hash,
            require_work=lambda: None)
    assert calls == []
