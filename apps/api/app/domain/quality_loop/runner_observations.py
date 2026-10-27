"""Verify runtime step observations, never infer business or build authority."""
from copy import deepcopy
import re


RUNNER_RECEIPT_SCHEMA = "nasus.runner-execution.v1"
ASSERTION_ACTIONS = frozenset({"assert_text", "assert_visible", "assert_url"})
RUNNER_ACTIONS = ASSERTION_ACTIONS | {"goto", "click", "fill", "press", "wait_for"}
_RECEIPT_FIELDS = frozenset({"schema", "runner_job_id", "project_id", "us_id", "request_hash",
    "execution_status", "step_count", "steps", "assertion_count", "observed_assertion_count",
    "passed_assertion_count", "failed_assertion_count", "target_build_verified", "business_coverage_verified"})


class RunnerObservationInvalid(ValueError):
    pass


def _verify_runner_observations(value, *, job_id, project_id, us_id, request_hash, step_actions, status,
                                schema, actions, assertions, fields):
    def require(condition):
        if not condition:
            raise RunnerObservationInvalid("runner execution receipt does not match the submitted job")

    require(type(value) is dict and set(value) == fields)
    require(value["schema"] == schema and value["runner_job_id"] == job_id
        and value["project_id"] == project_id and value["us_id"] == us_id
        and type(request_hash) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", request_hash)
        and value["request_hash"] == request_hash and value["execution_status"] == status
        and type(status) is str and status in {"passed", "failed", "error", "timed_out"})
    require(value["target_build_verified"] is False and value["business_coverage_verified"] is False)
    require(type(step_actions) is tuple and 1 <= len(step_actions) <= 100
        and all(type(action) is str and action in actions for action in step_actions))
    require(type(value["step_count"]) is int and value["step_count"] == len(step_actions)
        and type(value["steps"]) is list and len(value["steps"]) == len(step_actions))
    stopped = False
    failed_or_interrupted = False
    passed = failed = observed = 0
    for index, (action, step) in enumerate(zip(step_actions, value["steps"])):
        assertion = action in assertions
        require(type(step) is dict and set(step) == {"step_index", "action", "kind", "status"})
        require(type(step["step_index"]) is int and step["step_index"] == index and step["action"] == action
            and step["kind"] == ("assertion" if assertion else "action")
            and type(step["status"]) is str and step["status"] in {"passed", "failed", "interrupted", "not_executed"})
        if stopped:
            require(step["status"] == "not_executed")
        if step["status"] != "passed":
            stopped = True
        if step["status"] in {"failed", "interrupted"}:
            require(not failed_or_interrupted)
            failed_or_interrupted = True
        if assertion:
            passed += int(step["status"] == "passed")
            failed += int(step["status"] == "failed")
            observed += int(step["status"] in {"passed", "failed"})
    expected_counts = {"assertion_count": sum(action in assertions for action in step_actions),
        "passed_assertion_count": passed, "failed_assertion_count": failed, "observed_assertion_count": observed}
    require(all(type(value[key]) is int and value[key] == count for key, count in expected_counts.items()))
    require(status != "passed" or not stopped)
    return deepcopy(value)


def verify_runner_observations(value, *, job_id, project_id, us_id, request_hash, step_actions, status):
    return _verify_runner_observations(value, job_id=job_id, project_id=project_id, us_id=us_id,
        request_hash=request_hash, step_actions=step_actions, status=status, schema=RUNNER_RECEIPT_SCHEMA,
        actions=RUNNER_ACTIONS, assertions=ASSERTION_ACTIONS, fields=_RECEIPT_FIELDS)
