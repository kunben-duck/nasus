"""Protocol linkage tests only; no target or product acceptance is simulated."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from apps.api.app.application.quality_loop.browser_run_plan_observations import (
    BrowserRunPlanObservationApplicationService, ReviewedBrowserCommand,
)
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.browser_run_plan import compile_browser_case_jobs, verify_browser_receipt
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan
from apps.api.app.domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from apps.api.tests.test_run_plans import plan_inputs


ENVIRONMENT = acceptance_digest("protocol-environment-not-authority")
BROWSER = acceptance_digest("protocol-browser-not-authority")


def plan():
    draft, review, sources, selection = plan_inputs()
    return compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)


def commands(value):
    return BrowserRunPlanObservationApplicationService(None).commands(value, run_id="run-protocol", timeout_ms=5000,
        environment_digest=ENVIRONMENT, browser_digest=BROWSER)


def receipt(command, *, failed=False):
    job, stopped = command.wire(), False
    steps = []
    for index, step in enumerate(job["steps"]):
        assertion = step["action"].startswith("assert_")
        state = "not_executed" if stopped else "failed" if failed and assertion else "passed"
        stopped = stopped or state == "failed"
        steps.append(dict(step_index=index, action=step["action"], kind="assertion" if assertion else "action", status=state))
    assertions = [step for step in steps if step["kind"] == "assertion"]
    return dict(schema="nasus.runner-browser-execution.v1", runner_job_id=job["job_id"], project_id=job["project_id"],
        us_id=job["us_id"], request_hash=command.request_hash, execution_status="failed" if failed else "passed",
        step_count=len(steps), steps=steps, assertion_count=len(assertions),
        observed_assertion_count=sum(step["status"] in {"failed", "passed"} for step in assertions),
        passed_assertion_count=sum(step["status"] == "passed" for step in assertions),
        failed_assertion_count=sum(step["status"] == "failed" for step in assertions),
        target_build_verified=False, business_coverage_verified=False, reviewed_pins=job["reviewed_pins"],
        first_failed_assertion_index=next((step["step_index"] for step in steps if step["status"] == "failed"), None),
        write_fence="assertion_failed" if failed else "open", unknown_write_step_indices=[], private_evidence_stored=True)


def test_all_original_cases_actions_oracles_bound_without_promoting_coverage():
    value = plan()
    before = deepcopy(value)
    class NativeReader:
        def verify(self, command, result):
            assert result is None
            return receipt(command)
    app = BrowserRunPlanObservationApplicationService(NativeReader())
    for case, command in zip(value["prepared"]["cases"], commands(value)):
        observed = app.observe(value, command, None, run_id="run-protocol", environment_digest=ENVIRONMENT, browser_digest=BROWSER)
        assert observed["case_id"] == case["case_id"]
        assert {row["row_id"] for row in observed["oracles"]} == {row["row_id"] for row in case["assertions"]}
        assert observed["execution_authorized"] is observed["business_coverage_verified"] is False
        assert observed["executed_on_target_count"] == observed["passed_count"] == 0
    assert value == before


def test_current_runner_accepts_exact_python_wire_without_execution():
    # Cross-language contract check invokes validation only, never Chromium/network.
    command = commands(plan())[0]
    root = Path(__file__).resolve().parents[3]
    script = """import fs from 'node:fs';
import {validateBrowserJob} from './apps/runner/src/browser-job.mjs';
const wire=fs.readFileSync(0); const value=validateBrowserJob(JSON.parse(wire),wire);
process.stdout.write(value.inputHash);"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=command.request_body,
        cwd=root, capture_output=True, check=True)
    assert result.stdout.decode() == command.request_hash


@pytest.mark.parametrize("fault", ["foreign_case", "foreign_env", "foreign_browser", "actions", "request_hash",
    "schema", "false_success", "unarchived", "authority", "unknown_success", "boolean_count", "invented_failure"])
def test_receipt_refuses_rebound_or_promoted_results(fault):
    command = commands(plan())[0]
    value = receipt(command)
    if fault == "foreign_case": value["us_id"] = "other-case"
    elif fault == "foreign_env": value["reviewed_pins"]["environment_digest"] = acceptance_digest("other")
    elif fault == "foreign_browser": value["reviewed_pins"]["browser_digest"] = acceptance_digest("other")
    elif fault == "actions": value["steps"][0]["action"] = "evaluate"
    elif fault == "request_hash": value["request_hash"] = acceptance_digest("other")
    elif fault == "schema": value["schema"] = "nasus.runner-execution.v1"
    elif fault == "false_success": value["steps"][0]["status"] = "not_executed"
    elif fault == "unarchived": value["private_evidence_stored"] = False
    elif fault == "authority": value["business_coverage_verified"] = True
    elif fault == "unknown_success": value["unknown_write_step_indices"] = [0]
    elif fault == "boolean_count": value["step_count"] = True
    else: value["execution_status"] = "failed"
    with pytest.raises(ValueError):
        verify_browser_receipt(value, command.wire(), request_hash=command.request_hash, status=value["execution_status"])


def test_failure_keeps_unexecuted_oracles_instead_of_marking_passed():
    command = commands(plan())[0]
    value = receipt(command, failed=True)
    assert verify_browser_receipt(value, command.wire(), request_hash=command.request_hash, status="failed") == value
    assert any(step["status"] == "failed" for step in value["steps"])
    assert all(step["status"] == "not_executed" for step in value["steps"][value["first_failed_assertion_index"] + 1:])


@pytest.mark.parametrize("fault", ["environment", "browser", "run", "missing_native_reader", "wire"])
def test_application_requires_exact_cohort_and_private_native_reader(fault):
    value = plan()
    command = commands(value)[0]
    class Reader:
        def verify(self, *_):
            raise AssertionError("must reject before native read")
    app = BrowserRunPlanObservationApplicationService(None if fault == "missing_native_reader" else Reader())
    if fault == "wire":
        job = command.wire(); job["base_url"] = "http://foreign.invalid"
        command = ReviewedBrowserCommand(json.dumps(job).encode())
    with pytest.raises(RunPlanObservationInvalid):
        app.observe(value, command, None, run_id="other" if fault == "run" else "run-protocol",
            environment_digest=acceptance_digest("other") if fault == "environment" else ENVIRONMENT,
            browser_digest=acceptance_digest("other") if fault == "browser" else BROWSER)


def test_explicit_roster_rejects_http_rather_than_silently_omitting_it():
    from apps.api.tests.test_run_plan_observations import http_plan
    with pytest.raises(RunPlanObservationInvalid):
        commands(http_plan())


@pytest.mark.parametrize("timeout", [True, 999, 120001, 1000.0])
def test_deadline_and_runtime_pins_are_strict(timeout):
    with pytest.raises(RunPlanObservationInvalid):
        compile_browser_case_jobs(plan(), run_id="run", timeout_ms=timeout,
            environment_digest=ENVIRONMENT, browser_digest=BROWSER)
