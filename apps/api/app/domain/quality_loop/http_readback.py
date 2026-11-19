"""Versioned readback control: a failed oracle never permits another mutation."""
from copy import deepcopy
import re

from .http_bindings import HTTP_READBACK_RECEIPT_SCHEMA, validate_http_binding_steps
from .http_runner_oracles import _pointer, strict_http_json, same_http_json
from .runner_observations import RunnerObservationInvalid


HTTP_READBACK_SCHEMA = HTTP_READBACK_RECEIPT_SCHEMA
SNAPSHOT_ACTIONS = frozenset({"capture_snapshot", "assert_unchanged"})


def validate_readback_steps(steps, *, fixture_bindings=()):
    if type(steps) is not tuple or not 1 <= len(steps) <= 100:
        raise RunnerObservationInvalid("HTTP readback requires 1..100 original steps")
    projected, snapshots, requests = [], {}, {}
    mutation_seen = False
    for step in steps:
        if type(step) is not dict or type(step.get("action")) is not str:
            raise RunnerObservationInvalid("Invalid HTTP readback step")
        item = deepcopy(step)
        if step.get("action") == "request":
            phase = item.pop("phase", None)
            if (type(phase) is not str or type(step.get("method")) is not str or type(step.get("request_id")) is not str
                    or phase not in {"exercise", "readback"} or (phase == "readback" and step["method"] not in {"GET", "HEAD"})):
                raise RunnerObservationInvalid("HTTP readback must be an explicitly reviewed GET or HEAD")
            requests[step.get("request_id")] = (step.get("method"), phase)
            mutation_seen |= step.get("method") not in {"GET", "HEAD", "OPTIONS"}
        elif step.get("action") in SNAPSHOT_ACTIONS:
            if (type(step.get("request_id")) is not str
                    or set(step) - {"action", "request_id", "pointer", "snapshot_id", "source_step_indices"}):
                raise RunnerObservationInvalid("Invalid HTTP snapshot operands")
            ident = item.pop("snapshot_id", None)
            if type(ident) is not str or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", ident):
                raise RunnerObservationInvalid("Invalid HTTP snapshot identity")
            if step["action"] == "capture_snapshot":
                if mutation_seen or requests.get(step.get("request_id"), (None,))[0] != "GET":
                    raise RunnerObservationInvalid("HTTP before-state snapshots require a GET before any mutation")
                if ident in snapshots or len(snapshots) >= 32:
                    raise RunnerObservationInvalid("HTTP snapshots are bounded single assignments")
                snapshots[ident] = step.get("request_id")
            elif ident not in snapshots:
                raise RunnerObservationInvalid("HTTP unchanged assertion needs a preceding snapshot")
            elif (requests.get(step.get("request_id")) != ("GET", "readback")
                    or step.get("request_id") == snapshots[ident]):
                raise RunnerObservationInvalid("HTTP unchanged assertions require a subsequent GET")
            item.update(action="assert_json", value_json="null")
        projected.append(item)
    validate_http_binding_steps(tuple(projected), fixture_bindings=fixture_bindings)


def readback_step_allowed(step, *, failed, completed_requests):
    if not failed:
        return True
    if step["action"] == "request":
        return step["phase"] == "readback" and step["method"] in {"GET", "HEAD"}
    return step["action"].startswith("assert_") and step["request_id"] in completed_requests


def verify_readback_states(steps, states, status):
    failed, stopped, requests = False, False, set()
    for step, state in zip(steps, states):
        allowed = not stopped and readback_step_allowed(step, failed=failed, completed_requests=requests)
        if not allowed:
            if state != "not_executed":
                raise RunnerObservationInvalid("Failed HTTP assertions permit only reviewed readback, never another mutation")
            continue
        if state == "not_executed":
            stopped = True
        elif state == "interrupted":
            stopped = True
        elif state == "failed":
            if not step["action"].startswith("assert_"):
                raise RunnerObservationInvalid("HTTP non-assertion failures are interruptions")
            failed = True
        elif state == "passed" and step["action"] == "request":
            requests.add(step["request_id"])
    if ((status == "failed" and (not failed or stopped)) or (status == "passed" and (failed or stopped))
            or (status in {"error", "timed_out"} and not stopped)):
        raise RunnerObservationInvalid("HTTP final status hides incomplete readback or failed assertions")


def verify_snapshot_assertions(receipt, steps, responses):
    snapshots = {}
    for step, state in zip(steps, receipt["steps"]):
        if step["action"] not in SNAPSHOT_ACTIONS or state["status"] not in {"passed", "failed"}:
            continue
        try:
            response = responses[step["request_id"]]
            value = _pointer(strict_http_json(response["body"].decode("utf-8", errors="strict")), step["pointer"])
            if step["action"] == "capture_snapshot":
                if state["status"] != "passed" or not 200 <= response["status"] < 300:
                    raise RunnerObservationInvalid("HTTP snapshot requires its successful original response")
                snapshots[step["snapshot_id"]] = value
                continue
            matched = 200 <= response["status"] < 300 and same_http_json(snapshots[step["snapshot_id"]], value)
        except (KeyError, ValueError, UnicodeError):
            if step["action"] == "capture_snapshot":
                raise RunnerObservationInvalid("HTTP snapshot lacks original response proof") from None
            matched = False
        if matched is not (state["status"] == "passed"):
            raise RunnerObservationInvalid("HTTP unchanged assertion differs from original before/after evidence")
