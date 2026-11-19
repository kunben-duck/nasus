"""Browser wire contracts derived from reviewed plans, never execution authority."""
from copy import deepcopy
import re

from .acceptance_specification import acceptance_digest
from .run_plan_observations import RunPlanObservationInvalid, verify_plan
from .runner_observations import (
    ASSERTION_ACTIONS, RUNNER_ACTIONS, RunnerObservationInvalid,
    _RECEIPT_FIELDS, _verify_runner_observations,
)


BROWSER_RECEIPT_SCHEMA = "nasus.runner-browser-execution.v1"
BROWSER_OBSERVATION_SCHEMA = "nasus.run-plan-browser-observation.v1"
_EXTRA_FIELDS = {"reviewed_pins", "first_failed_assertion_index", "write_fence",
    "unknown_write_step_indices", "private_evidence_stored"}
_MUTATIONS = {"click", "fill", "press"}


def _require(condition):
    if not condition:
        raise RunPlanObservationInvalid("browser observation differs from its original reviewed plan")


def _digest(value):
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def compile_browser_case_jobs(plan, *, run_id, timeout_ms, environment_digest, browser_digest):
    """Convert an entire browser roster; do not silently omit HTTP cases or gaps."""
    verify_plan(plan)
    _require(type(run_id) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", run_id)
        and type(timeout_ms) is int and 1000 <= timeout_ms <= 120000
        and _digest(environment_digest) and _digest(browser_digest))
    scripts = {script["case_id"]: script for script in plan["proposal"]["scripts"]}
    jobs = []
    for case in plan["prepared"]["cases"]:
        script = scripts[case["case_id"]]
        _require(script["kind"] == "browser" and 1 <= len(script["actions"]) <= 100)
        pins = dict(plan_digest=plan["plan_digest"], script_digest=acceptance_digest(script),
            case_digest=acceptance_digest(case), environment_digest=environment_digest, browser_digest=browser_digest)
        identity = acceptance_digest([BROWSER_RECEIPT_SCHEMA, run_id, pins, timeout_ms]).split(":", 1)[1]
        jobs.append(dict(job_id="run-plan-browser-" + identity, project_id=plan["project_id"], us_id=case["case_id"],
            execution_kind="browser", receipt_protocol=BROWSER_RECEIPT_SCHEMA,
            base_url=plan["selection"]["environment"]["base_url"], timeout_ms=timeout_ms,
            reviewed_pins=pins, steps=deepcopy(script["actions"])))
    return tuple(jobs)


def verify_browser_receipt(receipt, job, *, request_hash, status):
    """Verify ordering and reviewed readback; private evidence still needs a native reader."""
    _require(type(receipt) is dict and set(receipt) == _RECEIPT_FIELDS | _EXTRA_FIELDS
        and receipt["reviewed_pins"] == job["reviewed_pins"]
        and type(receipt["private_evidence_stored"]) is bool)
    unknown = receipt["unknown_write_step_indices"]
    _require(type(unknown) is list and all(type(index) is int and 0 <= index < len(job["steps"]) for index in unknown)
        and unknown == sorted(set(unknown))
        and all(job["steps"][index]["action"] not in ASSERTION_ACTIONS for index in unknown))
    fence = receipt["write_fence"]
    _require(type(fence) is str and fence in {"open", "assertion_failed", "unknown_write", "interrupted", "policy_rejected"}
        and (not unknown or fence == "unknown_write" and status in {"error", "timed_out"}))
    first_failed = receipt["first_failed_assertion_index"]
    _require(first_failed is None or type(first_failed) is int and 0 <= first_failed < len(job["steps"]))

    def continuation(states, execution_status):
        failures = [index for index, state in enumerate(states) if state == "failed"]
        _require(all(job["steps"][index]["action"] in ASSERTION_ACTIONS for index in failures)
            and first_failed == (failures[0] if failures else None))
        blocked = False
        terminal = False
        for index, (step, state) in enumerate(zip(job["steps"], states)):
            if terminal:
                _require(state == "not_executed")
            if blocked and state != "not_executed":
                _require(step.get("phase") == "verification" and step["action"] not in _MUTATIONS)
            if index in unknown:
                _require(state in {"interrupted", "passed"})
                # A request may become unknown only after its initiating step
                # returned. Such late evidence still makes the whole result unknown.
                blocked = blocked or state == "interrupted"
            if state == "failed":
                blocked = True
            if state == "interrupted" and index not in unknown:
                terminal = True
            if state == "not_executed" and not blocked:
                terminal = True
        _require(execution_status != "failed" or bool(failures) and not unknown)
        _require(execution_status != "passed" or fence == "open" and not unknown
            and not failures and receipt["private_evidence_stored"] is True)
        _require(not failures or fence != "open")
        _require(fence != "assertion_failed" or bool(failures))
        _require(fence != "unknown_write" or bool(unknown))

    try:
        return _verify_runner_observations(receipt, job_id=job["job_id"], project_id=job["project_id"],
            us_id=job["us_id"], request_hash=request_hash, step_actions=tuple(step["action"] for step in job["steps"]),
            status=status, schema=BROWSER_RECEIPT_SCHEMA, actions=RUNNER_ACTIONS, assertions=ASSERTION_ACTIONS,
            fields=_RECEIPT_FIELDS | _EXTRA_FIELDS, continuation=continuation)
    except (KeyError, TypeError, RunnerObservationInvalid):
        raise RunPlanObservationInvalid("browser receipt cannot be verified") from None


def map_browser_case_observation(plan, job, receipt, *, run_id, request_hash):
    """Link original case oracles. Runtime counts are not product coverage or permission."""
    jobs = compile_browser_case_jobs(plan, run_id=run_id, timeout_ms=job["timeout_ms"],
        environment_digest=job["reviewed_pins"]["environment_digest"], browser_digest=job["reviewed_pins"]["browser_digest"])
    _require(job in jobs)
    checked = verify_browser_receipt(receipt, job, request_hash=request_hash, status=receipt["execution_status"])
    case = next(item for item in plan["prepared"]["cases"] if item["case_id"] == job["us_id"])
    script = next(item for item in plan["proposal"]["scripts"] if item["case_id"] == job["us_id"])
    value = dict(schema=BROWSER_OBSERVATION_SCHEMA, project_id=plan["project_id"], run_id=run_id,
        case_id=case["case_id"], case_digest=acceptance_digest(case), plan_digest=plan["plan_digest"],
        reviewed_pins=deepcopy(job["reviewed_pins"]),
        context_pin=deepcopy(plan["prepared"]["context_pin"]), script_pin=deepcopy(plan["script_pin"]),
        review_pin=deepcopy(plan["review_pin"]), status=checked["execution_status"], runner_receipt=checked,
        oracles=[{key: assertion[key] for key in ("row_id", "action_index", "source_step_index", "oracle_digest")}
            | {"status": checked["steps"][assertion["action_index"]]["status"]} for assertion in script["assertions"]],
        execution_authorized=False, target_build_verified=False, business_coverage_verified=False,
        automated_count=0, executed_on_target_count=0, passed_count=0)
    return {**value, "observation_digest": acceptance_digest(value)}
