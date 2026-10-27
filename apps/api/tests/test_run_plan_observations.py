"""Original case/oracle linkage, not environment or execution authorization."""
from copy import deepcopy
from dataclasses import replace
import base64
import hashlib
import json

import pytest

from apps.api.app.application.quality_loop.run_plan_observations import RunPlanObservationApplicationService
from apps.api.app.application.quality_loop.runner_port import AutomationRunnerResult, RunnerArtifact
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_scripts import validate_script_proposal
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan
from apps.api.app.domain.quality_loop.run_plan_observations import RunPlanObservationInvalid, collect_run_plan_observations
from apps.api.app.infrastructure.runner.request_wire import runner_request_hash
from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
from apps.api.tests.test_automation_scripts import script_output
from apps.api.tests.test_run_plans import plan_inputs, selection_for


def observation_service():
    return RunPlanObservationApplicationService(HTTPRunnerObservationVerifier())


def http_plan(base_url="http://127.0.0.1:19876", request_path=None):
    draft, review, sources, _selection = plan_inputs()
    prepared = draft["result"]["prepared"]
    output = script_output(prepared, kind="http")
    if request_path is not None:
        for script in output["scripts"]:
            for action in script["actions"]:
                if action["action"] == "request": action["path"] = request_path
    draft["result"]["proposal"] = validate_script_proposal(prepared, output)
    draft["metadata"]["artifact_hash"] = acceptance_digest(draft["result"])
    review["revision"]["script_artifact_hash"] = draft["metadata"]["artifact_hash"]
    selection = selection_for(draft, review, sources).model_dump(mode="json")
    selection["environment"]["base_url"] = base_url
    return compile_run_plan(draft, review, selection, sources)


def protocol_result(command, *, failed=False):
    """Physically bound response specimen, independent from the claimed status."""
    steps, requests, artifacts = [], [], []
    stopped = False
    for index, action in enumerate(command.steps):
        state = "not_executed" if stopped else "failed" if failed and action["action"] != "request" else "passed"
        stopped |= state == "failed"
        steps.append(dict(step_index=index, action=action["action"], kind="action" if action["action"] == "request" else "assertion", status=state))
        if action["action"] == "request" and state == "passed":
            from apps.api.app.domain.quality_loop.http_runner_observations import http_step_input_hash
            body = ("actual missing oracle" if failed else " ".join(step.get("value", "") for step in command.steps)).encode()
            observed = dict(request_id=action["request_id"], step_index=index, method=action["method"],
                input_hash=http_step_input_hash(action), response_status=200, response_byte_count=len(body),
                response_hash="sha256:" + hashlib.sha256(body).hexdigest())
            metadata = json.dumps(dict(schema="nasus.http-response.v1", **observed, headers={})).encode()
            requests.append(dict(**observed, response_metadata_hash="sha256:" + hashlib.sha256(metadata).hexdigest()))
            for suffix, wire, media in ((".bin", body, "application/octet-stream"), (".json", metadata, "application/json")):
                artifacts.append(RunnerArtifact("report", "http-response-" + action["request_id"] + suffix, media, base64.b64encode(wire).decode()))
    status = "failed" if failed else "passed"
    assertions = [step for step in steps if step["kind"] == "assertion"]
    receipt = dict(schema="nasus.runner-http-execution.v1", runner_job_id=command.job_id, project_id=command.project_id,
        us_id=command.us_id, request_hash=runner_request_hash(command), execution_status=status, step_count=len(steps), steps=steps,
        assertion_count=len(assertions), observed_assertion_count=sum(step["status"] in {"passed", "failed"} for step in assertions),
        passed_assertion_count=sum(step["status"] == "passed" for step in assertions),
        failed_assertion_count=sum(step["status"] == "failed" for step in assertions),
        target_build_verified=False, business_coverage_verified=False, requests=requests)
    artifacts.append(RunnerArtifact("report", "http-execution.json", "application/json", base64.b64encode(json.dumps(receipt).encode()).decode()))
    return AutomationRunnerResult(command.job_id, status, "explicit response specimen", "", "start", "end",
        artifacts=tuple(artifacts), runner_mode="http_native", execution_receipt=receipt)


def test_commands_and_observations_preserve_every_original_case_step_and_oracle():
    plan = http_plan()
    original = deepcopy(plan)
    service = observation_service()
    commands = service.commands(plan, run_id="explicit-internal-attempt", timeout_ms=5000)
    observations = []
    for case, command in zip(plan["prepared"]["cases"], commands):
        assert command.kind == "http" and command.us_id == case["case_id"]
        script = next(item for item in plan["proposal"]["scripts"] if item["case_id"] == case["case_id"])
        assert list(command.steps) == script["actions"]
        assert command.metadata["case_digest"] == acceptance_digest(case)
        observed = service.observe_http(plan, command, protocol_result(command))
        assert observed["case_id"] == case["case_id"] and observed["case_digest"] == acceptance_digest(case)
        assert {item["row_id"] for item in observed["oracles"]} == {item["row_id"] for item in case["assertions"]}
        assert all(item["status"] == "passed" for item in observed["oracles"])
        assert observed["fixture_digest"] == acceptance_digest(next(item for item in plan["selection"]["fixtures"] if item["case_id"] == case["case_id"]))
        observations.append(observed)
    summary = collect_run_plan_observations(plan, observations)
    assert summary["observed_case_count"] == summary["passed_observation_count"] == len(commands)
    assert summary["automated_count"] == summary["executed_on_target_count"] == summary["passed_count"] == 0
    assert summary["business_coverage_verified"] is summary["execution_authorized"] is False
    assert plan == original


def test_failed_oracle_preserves_unexecuted_rows_and_missing_cases():
    plan, service = http_plan(), observation_service()
    command = service.commands(plan, run_id="attempt", timeout_ms=5000)[0]
    observed = service.observe_http(plan, command, protocol_result(command, failed=True))
    assert observed["status"] == "failed"
    states = [item["status"] for item in observed["oracles"]]
    assert states[0] == "failed" and all(state == "not_executed" for state in states[1:])
    summary = collect_run_plan_observations(plan, [observed])
    assert summary["observed_case_count"] == 1 and summary["passed_observation_count"] == 0
    assert summary["not_executed_case_count"] == len(plan["prepared"]["cases"]) - 1
    assert any(item["status"] == "not_executed" for item in summary["cases"])


@pytest.mark.parametrize("fault", ["plan_hash", "authority", "boolean_count", "missing_case", "changed_oracle", "missing_fixture", "script_hash"])
def test_compile_rejects_rehashed_invalid_plan_not_just_bad_digest(fault):
    plan = http_plan()
    if fault == "plan_hash": plan["plan_digest"] = acceptance_digest("other")
    elif fault == "authority": plan["execution_authorized"] = True
    elif fault == "boolean_count": plan["passed_count"] = False
    elif fault == "missing_case": plan["prepared"]["cases"].pop()
    elif fault == "changed_oracle": plan["proposal"]["scripts"][0]["assertions"][0]["oracle_digest"] = acceptance_digest("other")
    elif fault == "missing_fixture": plan["selection"]["fixtures"].pop()
    else: plan["script_pin"]["proposal_hash"] = acceptance_digest("other")
    if fault != "plan_hash": plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    with pytest.raises(RunPlanObservationInvalid):
        observation_service().commands(plan, run_id="attempt", timeout_ms=5000)


@pytest.mark.parametrize("fault", ["origin", "case", "action", "metadata", "job", "timeout", "mode", "response_bytes", "receipt", "authority"])
def test_observation_rejects_different_job_and_response_before_mapping(fault):
    plan, service = http_plan(), observation_service()
    command = service.commands(plan, run_id="attempt", timeout_ms=5000)[0]
    result = protocol_result(command)
    if fault == "origin": command = replace(command, base_url="http://unreviewed.invalid")
    elif fault == "case": command = replace(command, us_id="other-case")
    elif fault == "action": command = replace(command, steps=({**command.steps[0], "path": "/another"}, *command.steps[1:]))
    elif fault == "metadata": command = replace(command, metadata={**command.metadata, "case_digest": acceptance_digest("other")})
    elif fault == "job": command = replace(command, job_id="another-job")
    elif fault == "timeout": command = replace(command, timeout_ms=6000)
    elif fault == "mode": result = replace(result, runner_mode="mock")
    elif fault == "response_bytes":
        first, *others = result.artifacts
        result = replace(result, artifacts=(replace(first, content_base64=base64.b64encode(b"forged").decode()), *others))
    elif fault == "receipt": result = replace(result, execution_receipt=None)
    else: result.execution_receipt["business_coverage_verified"] = True
    with pytest.raises(ValueError): service.observe_http(plan, command, result)


@pytest.mark.parametrize("fault", ["duplicate", "plan", "case", "oracle", "status", "mixed_attempt"])
def test_collection_rejects_rehashed_foreign_duplicate_or_changed_case_observations(fault):
    plan, service = http_plan(), observation_service()
    commands = service.commands(plan, run_id="attempt", timeout_ms=5000)
    first = service.observe_http(plan, commands[0], protocol_result(commands[0]))
    items = [first]
    if fault == "duplicate": items.append(deepcopy(first))
    elif fault == "plan": first["plan_digest"] = acceptance_digest("other")
    elif fault == "case": first["case_id"] = "other"
    elif fault == "oracle": first["oracles"][0]["oracle_digest"] = acceptance_digest("other")
    elif fault == "status": first["status"] = "not_executed"
    else:
        other = service.commands(plan, run_id="other-attempt", timeout_ms=5000)[1]
        items.append(service.observe_http(plan, other, protocol_result(other)))
    if fault != "duplicate": first["observation_digest"] = acceptance_digest({key: value for key, value in first.items() if key != "observation_digest"})
    with pytest.raises(RunPlanObservationInvalid): collect_run_plan_observations(plan, items)


@pytest.mark.parametrize("timeout", [True, 0, 999, 120001, 5000.0])
def test_invalid_deadline_cannot_create_a_partial_command_roster(timeout):
    with pytest.raises(RunPlanObservationInvalid):
        observation_service().commands(http_plan(), run_id="attempt", timeout_ms=timeout)


def test_batch_compiles_once_and_physically_verifies_every_original_result(monkeypatch):
    from apps.api.app.application.quality_loop import run_plan_observations as application
    plan, service = http_plan(), observation_service()
    commands = service.commands(plan, run_id="attempt", timeout_ms=5000)
    entries = [(item, protocol_result(item, failed=index == 0)) for index, item in enumerate(commands)]
    compile_original = application.compile_case_jobs
    compiled = []
    monkeypatch.setattr(application, "compile_case_jobs", lambda *args, **kwargs:
        (compiled.append(True), compile_original(*args, **kwargs))[1])
    value = service.observe_http_batch(plan, list(reversed(entries)), run_id="attempt", timeout_ms=5000)
    assert len(compiled) == 1
    assert [item["case_id"] for item in value] == [item["case_id"] for item in plan["prepared"]["cases"]]
    assert value[0]["status"] == "failed" and all(item["status"] == "passed" for item in value[1:])


@pytest.mark.parametrize("fault", ["foreign_job", "partial_artifacts", "passed_without_receipt"])
def test_attempt_batch_checks_every_original_job_before_verifying_any_response(monkeypatch, fault):
    plan, service = http_plan(), observation_service()
    commands = service.commands(plan, run_id="attempt", timeout_ms=5000)
    entries = [(item, protocol_result(item)) for item in commands]
    command, result = entries[-1]
    uncertain = replace(result, status="error", execution_receipt=None, artifacts=())
    if fault == "foreign_job": command = replace(command, job_id="other-attempt")
    elif fault == "partial_artifacts": uncertain = replace(uncertain, artifacts=result.artifacts)
    else: uncertain = replace(uncertain, status="passed")
    entries[-1] = (command, uncertain)
    verified = []
    monkeypatch.setattr(service.verifier, "verify", lambda *args: verified.append(args))
    with pytest.raises(RunPlanObservationInvalid):
        service.observe_http_attempt_batch(plan, entries, run_id="attempt", timeout_ms=5000)
    assert verified == []


@pytest.mark.parametrize("fault", ["duplicate", "foreign", "changed_job", "missing_receipt"])
def test_batch_rejects_invalid_later_job_before_inspecting_any_responses(fault):
    plan, service = http_plan(), observation_service()
    commands = service.commands(plan, run_id="attempt", timeout_ms=5000)
    entries = [(item, protocol_result(item)) for item in commands]
    if fault == "duplicate": entries[1] = entries[0]
    elif fault == "foreign": entries[1] = (replace(commands[1], job_id="foreign-job"), entries[1][1])
    elif fault == "changed_job": entries[1] = (replace(commands[1], base_url="http://unreviewed.invalid"), entries[1][1])
    else: entries[1] = (commands[1], replace(entries[1][1], execution_receipt=None))
    seen = []
    service.verifier = type("NeverInspectInvalidCohort", (), {"verify": lambda _self, *args: seen.append(args)})()
    with pytest.raises(RunPlanObservationInvalid): service.observe_http_batch(plan, entries, run_id="attempt", timeout_ms=5000)
    assert seen == []


def test_native_http_preflight_rejects_a_later_case_without_returning_an_earlier_job():
    plan = http_plan()
    plan["proposal"]["scripts"][-1]["actions"][0]["body_json"] = '{"invalid_get_body":true}'
    plan["script_pin"]["proposal_hash"] = acceptance_digest(plan["proposal"])
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    with pytest.raises(RunPlanObservationInvalid): observation_service().commands(plan, run_id="attempt", timeout_ms=5000)
