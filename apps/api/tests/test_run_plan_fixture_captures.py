"""Physical verifier specimens and pure capture handoff; not native target gold."""
import base64
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from apps.api.app.application.quality_loop.http_fixtures import HttpFixturePhaseRecord
from apps.api.app.application.quality_loop.runner_port import RunnerArtifact
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_bindings import http_binding_value_hash
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.app.domain.quality_loop.run_plan_fixture_captures import (
    CaseFixtureCaptures, FixtureResourceCapture, collect_case_fixture_captures,
)
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.request_wire import runner_request_hash
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec


def read_sources(value):
    prepared = value.service.prepare(value.selection, invocation_id=value.snapshot["id"])
    proofs = tuple(value.fixtures.read(value.selection.project_id, selected.invocation_id,
        require_current=lambda: None) for selected in value.selection.fixture_setups)
    return prepared, proofs


def test_producer_preserves_every_original_capture_without_dispatch_or_legacy_path_rewrite(case_inputs):
    v = case_inputs
    prepared, proofs = read_sources(v)
    captures = prepared.fixture_captures
    assert captures == collect_case_fixture_captures(prepared.plan, prepared.scope, proofs)
    assert tuple(item.case_id for item in captures) == tuple(item.case_id for item in v.selection.fixture_setups)
    assert tuple(item.setup_invocation_id for item in captures) == tuple(item.invocation_id for item in v.selection.fixture_setups)
    for value, source in zip(captures, proofs):
        assert type(value) is CaseFixtureCaptures and value.scope_digest == prepared.scope.digest
        assert all(type(item) is FixtureResourceCapture for item in value.captures)
        assert value.setup_request_hash == source["setup_request_hash"]
        assert value.setup_result_hash == source["setup_result_hash"]
        assert value.setup_history_digest == source["history_digest"]
        assert value.captures[0].value == source["receipt"]["bindings"][0]["value"]
        assert value.captures[0].response_hash == source["receipt"]["bindings"][0]["response_hash"]
        assert "value=" not in repr(value.captures[0]) and "captures=" not in repr(value)
    v.service.require_current(prepared)
    assert len(v.runner.commands) == v.state["initial_request_count"]
    assert prepared.plan == v.v.saved["artifact"]["plan"]


def test_capture_handoff_is_immutable_and_does_not_alias_the_source_receipt(case_inputs):
    prepared, proofs = read_sources(case_inputs)
    values = collect_case_fixture_captures(prepared.plan, prepared.scope, proofs)
    original = values[0].digest
    resource = values[0].captures[0].value
    proofs[0]["receipt"]["bindings"][0]["value"] = "caller_mutated_resource"
    assert values[0].captures[0].value == resource and values[0].digest == original
    with pytest.raises(FrozenInstanceError):
        values[0].captures[0].value = "caller_mutated_resource"


@pytest.mark.parametrize("fault", ["missing_case", "extra_case", "reordered_cases", "setup_command", "source_extra",
    "history_hash", "wire_hash", "request_hash", "plan", "case", "target", "inventory", "environment_record",
    "manifest_hash", "receipt_job", "receipt_case", "receipt_schema", "receipt_failed", "partial_steps",
    "partial_captures", "duplicate_capture", "capture_step", "capture_pointer", "capture_request", "capture_source",
    "capture_value_hash", "capture_value_escape", "capture_flag", "capture_boolean_index", "request_reorder"])
def test_complete_handoff_rejects_missing_rebound_or_unverified_source_fields(case_inputs, fault):
    prepared, source = read_sources(case_inputs)
    proofs = list(deepcopy(source))
    value = proofs[0]
    if fault == "missing_case": proofs.pop()
    elif fault == "extra_case": proofs.append(deepcopy(proofs[0]))
    elif fault == "reordered_cases": proofs.reverse()
    elif fault == "setup_command": value["invocation_id"] = "other-original-setup"
    elif fault == "source_extra": value["verified"] = True
    elif fault == "history_hash": value["history_digest"] = "unverified"
    elif fault == "wire_hash": value["setup_result_hash"] = "unverified"
    elif fault == "request_hash": value["setup_request_hash"] = acceptance_digest("other original request")
    elif fault == "plan": value["parent"]["run_plan_id"] = "other-original-plan"
    elif fault == "case": value["scope"]["case_id"] = "other-original-case"
    elif fault == "target": value["scope"]["artifact_hash"] = acceptance_digest("other target")
    elif fault == "inventory": value["scope"]["inventory_hash"] = acceptance_digest("other inventory")
    elif fault == "environment_record": value["native_environment"]["record_id"] = "other-environment"
    elif fault == "manifest_hash": value["scope"]["data_manifest_hash"] = acceptance_digest("other recipe")
    elif fault == "receipt_job": value["receipt"]["runner_job_id"] = "other-original-job"
    elif fault == "receipt_case": value["receipt"]["us_id"] = "other-original-case"
    elif fault == "receipt_schema": value["receipt"]["schema"] = "nasus.runner-http-execution.v1"
    elif fault == "receipt_failed": value["receipt"]["execution_status"] = "failed"
    elif fault == "partial_steps": value["receipt"]["steps"].pop()
    elif fault == "partial_captures": value["receipt"]["bindings"].clear()
    elif fault == "duplicate_capture": value["receipt"]["bindings"].append(deepcopy(value["receipt"]["bindings"][0]))
    elif fault == "request_reorder": value["receipt"]["requests"].append(deepcopy(value["receipt"]["requests"][0]))
    else:
        capture = value["receipt"]["bindings"][0]
        if fault == "capture_step": capture["step_index"] += 1
        elif fault == "capture_pointer": capture["pointer"] = "/other_field"
        elif fault == "capture_request": capture["request_id"] = "other-original-request"
        elif fault == "capture_source": capture["response_hash"] = acceptance_digest("other response")
        elif fault == "capture_value_hash": capture["value_hash"] = acceptance_digest("other resource")
        elif fault == "capture_value_escape": capture["value"] = "../another/resource"
        elif fault == "capture_flag": capture["verified"] = True
        elif fault == "capture_boolean_index": capture["step_index"] = True
    with pytest.raises(RunPlanCaseExecutionInvalid):
        collect_case_fixture_captures(prepared.plan, prepared.scope, tuple(proofs))
    assert len(case_inputs.runner.commands) == case_inputs.state["initial_request_count"]


def test_rehashed_capture_value_cannot_replace_the_actual_setup_response(case_inputs):
    v = case_inputs
    phase = v.state["phases"][0][1]
    execution = phase.execution
    # Change both reported copies and their hashes, but not the original source response bytes.
    payload = json.loads(execution.result_body)
    receipt = payload["execution_receipt"]
    receipt["bindings"][0]["value"] = "self_consistent_fake_resource"
    receipt["bindings"][0]["value_hash"] = http_binding_value_hash("self_consistent_fake_resource")
    for artifact in payload["artifacts"]:
        if artifact["name"] == "http-execution.json":
            artifact["content_base64"] = base64.b64encode(json.dumps(receipt).encode()).decode()
    with pytest.raises(ValueError, match="differs from its original JSON response"):
        HttpAutomationRunner._result_from_payload(phase.command, payload, request_hash=runner_request_hash(phase.command))
    result = replace(execution.result, execution_receipt=deepcopy(receipt),
        artifacts=tuple(RunnerArtifact(**artifact) for artifact in payload["artifacts"]))
    forged = replace(execution, result=result, result_body=json.dumps(payload).encode())
    v.state["phases"] = (("setup", HttpFixturePhaseRecord(phase.command, forged)), v.state["phases"][1])
    with pytest.raises(ValueError):
        v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    assert len(v.runner.commands) == v.state["initial_request_count"]


def test_current_input_guard_rebuilds_captures_instead_of_trusting_a_caller_rehashed_value(case_inputs):
    v = case_inputs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    original = prepared.fixture_captures[0]
    resource = replace(original.captures[0], value="caller_resource", value_hash=http_binding_value_hash("caller_resource"))
    changed = replace(original, captures=(resource, *original.captures[1:]))
    forged = replace(prepared, fixture_captures=(changed, *prepared.fixture_captures[1:]))
    assert changed.digest != original.digest
    with pytest.raises(RunPlanChanged):
        v.service.require_current(forged)
    assert len(v.runner.commands) == v.state["initial_request_count"]
