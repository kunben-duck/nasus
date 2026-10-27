"""A runner status alone is not an observation of the submitted assertions."""
from copy import deepcopy

import httpx
import pytest

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.request_wire import runner_request_hash
from apps.api.app.domain.quality_loop.runner_observations import (
    ASSERTION_ACTIONS, RUNNER_RECEIPT_SCHEMA, RunnerObservationInvalid, verify_runner_observations,
)


def make_receipt(value, *, status="passed", step_statuses=None):
    states = step_statuses or ["passed"] * len(value.steps)
    steps = [{"step_index": index, "action": step["action"],
        "kind": "assertion" if step["action"] in ASSERTION_ACTIONS else "action", "status": states[index]}
        for index, step in enumerate(value.steps)]
    assertions = [step for step in steps if step["kind"] == "assertion"]
    return {"schema": RUNNER_RECEIPT_SCHEMA, "runner_job_id": value.job_id,
        "project_id": value.project_id, "us_id": value.us_id, "request_hash": runner_request_hash(value),
        "execution_status": status, "step_count": len(steps), "steps": steps,
        "assertion_count": len(assertions), "observed_assertion_count": sum(s["status"] in {"passed", "failed"} for s in assertions),
        "passed_assertion_count": sum(s["status"] == "passed" for s in assertions),
        "failed_assertion_count": sum(s["status"] == "failed" for s in assertions),
        "target_build_verified": False, "business_coverage_verified": False}


def verify(receipt, value=None, *, status="passed"):
    value = value or command()
    return verify_runner_observations(receipt, job_id=value.job_id, project_id=value.project_id,
        us_id=value.us_id, request_hash=runner_request_hash(value),
        step_actions=tuple(step["action"] for step in value.steps), status=status)


def command():
    return AutomationRunnerCommand(job_id="receipt-job", project_id="receipt-project", us_id="receipt-us",
        base_url="http://127.0.0.1:32123", timeout_ms=2000,
        steps=({"action": "goto", "path": "/"}, {"action": "assert_text", "selector": "h1", "text": "订单已退款"}))


def response_payload():
    return {"runner_job_id": "receipt-job", "status": "passed", "summary": "passed",
        "failure_summary": "", "started_at": "2026-10-10T00:00:00Z", "completed_at": "2026-10-10T00:00:01Z",
        "timeline": ["Step 1", "Step 2"], "artifacts": []}


def execute_response(monkeypatch, payload):
    class Response:
        def raise_for_status(self): pass
        def json(self): return deepcopy(payload)

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Response())
    return HttpAutomationRunner("http://runner.test:8090", "private-service-token").execute(command())


@pytest.mark.parametrize("change", ["missing", "different_job", "caller_receipt"])
def test_http_runner_rejects_unbound_pass_status(monkeypatch, change):
    payload = response_payload()
    if change == "different_job":
        payload["runner_job_id"] = "some-other-job"
    if change == "caller_receipt":
        payload["execution_receipt"] = {"schema": "nasus.runner-execution.v1", "passed_assertion_count": 999,
            "business_coverage_verified": True, "target_build_verified": True}
    result = execute_response(monkeypatch, payload)
    assert result.status == "error"
    assert result.runner_job_id == "receipt-job"
    assert not result.artifacts
    assert "订单" not in result.failure_summary


def test_independent_runner_receipt_is_bound_and_not_business_authority(monkeypatch):
    original = make_receipt(command())
    assert verify(original) == original
    copied = verify(original)
    copied["steps"][0]["status"] = "failed"
    assert original["steps"][0]["status"] == "passed"
    payload = response_payload()
    payload["execution_receipt"] = original
    result = execute_response(monkeypatch, payload)
    assert result.status == "passed"
    assert result.execution_receipt == original
    assert result.execution_receipt["passed_assertion_count"] == 1
    assert not result.execution_receipt["business_coverage_verified"]


@pytest.mark.parametrize("field,new", [("project_id", "other-project"), ("us_id", "other-us"),
    ("runner_job_id", "other-job"), ("request_hash", "sha256:" + "0" * 64), ("execution_status", "failed"),
    ("schema", "future-schema"), ("step_count", True), ("assertion_count", 99),
    ("observed_assertion_count", True), ("passed_assertion_count", 99), ("failed_assertion_count", 1),
    ("business_coverage_verified", True), ("target_build_verified", True), ("steps", [])])
def test_receipt_scope_counts_and_authority_cannot_be_forged(monkeypatch, field, new):
    receipt = make_receipt(command())
    receipt[field] = new
    with pytest.raises(RunnerObservationInvalid):
        verify(receipt)
    payload = response_payload()
    payload["execution_receipt"] = receipt
    assert execute_response(monkeypatch, payload).status == "error"


@pytest.mark.parametrize("change", ["reorder", "action", "kind", "unexecuted", "bool_index", "extra", "missing", "bad_status"])
def test_receipt_has_every_original_step_exactly_once(change):
    receipt = make_receipt(command())
    if change == "reorder": receipt["steps"].reverse()
    if change == "action": receipt["steps"][1]["action"] = "wait_for"
    if change == "kind": receipt["steps"][1]["kind"] = "action"
    if change == "unexecuted": receipt["steps"][0]["status"] = "not_executed"
    if change == "bool_index": receipt["steps"][0]["step_index"] = False
    if change == "extra": receipt["approved_case_ids"] = ["caller-case"]
    if change == "missing": del receipt["business_coverage_verified"]
    if change == "bad_status": receipt["steps"][0]["status"] = []
    with pytest.raises(RunnerObservationInvalid): verify(receipt)


@pytest.mark.parametrize("status,states,observed,failed", [
    ("failed", ["passed", "failed"], 1, 1),
    ("failed", ["failed", "not_executed"], 0, 0),
    ("timed_out", ["passed", "interrupted"], 0, 0),
    ("error", ["not_executed", "not_executed"], 0, 0),
])
def test_partial_execution_does_not_invent_later_assertions(status, states, observed, failed):
    receipt = make_receipt(command(), status=status, step_statuses=states)
    assert verify(receipt, status=status) == receipt
    assert receipt["observed_assertion_count"] == observed
    assert receipt["failed_assertion_count"] == failed


def test_navigation_only_success_has_no_assertion_or_coverage():
    value = command()
    value = AutomationRunnerCommand(**{**value.__dict__, "steps": (value.steps[0],)})
    receipt = verify(make_receipt(value), value)
    assert receipt["assertion_count"] == receipt["passed_assertion_count"] == 0
    assert receipt["business_coverage_verified"] is False


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_default_timeline_cannot_invent_approved_cases_or_business_validation(status):
    from apps.api.app.infrastructure.runner.run_orchestrator import RunOrchestrator

    text = " ".join(RunOrchestrator._default_timeline(status)).lower()
    assert "approved cases" not in text and "generated browser automation" not in text
    if status == "passed":
        assert "business coverage remains unverified" in text
