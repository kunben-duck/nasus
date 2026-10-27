"""Original journal observations cannot authorize retry or certify coverage."""
import re

from .http_fixture_command import FALSE_AUTHORITIES, FIXTURE_OBSERVATION_TOOL
from .acceptance_specification import acceptance_digest
from .http_fixtures import HttpFixtureInvalid


FIXTURE_OBSERVATION_SCHEMA = "nasus.http-fixture-original-observation.v1"
FIXTURE_OBSERVATION_KIND = "original_persisted_journal_not_live_target"


class HttpFixtureObservationChanged(ValueError):
    pass


def _require(condition):
    if not condition:
        raise HttpFixtureInvalid("original fixture observation lost its complete journal, ancestry or non-authority")


def _digest(value):
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def classify_original_observation(selected, execution, expected_phases, job):
    """Unknown survives cancellation; completion requires every original phase."""
    try:
        return _classify(selected, execution, expected_phases, job)
    except (KeyError, TypeError, AttributeError) as exc:
        raise HttpFixtureInvalid("original fixture journal shape cannot be verified") from exc


def _classify(selected, execution, expected_phases, job):
    if selected["stage"] == "grant":
        _require(execution is None and job is None and expected_phases == [])
        return "not_execution"
    _require(type(execution) is dict and execution["stage"] == "execute"
        and (selected["stage"] != "execute" or selected == execution)
        and selected["original_execution_id"] == execution["invocation_id"]
        and all(selected[key] == execution[key] for key in ("project_id", "recipe_id", "recipe_artifact_hash",
            "run_plan_id", "run_plan_artifact_hash", "case_id", "attempt_id", "operation", "grant_id", "grant_digest")))
    if execution["status"] in {"pending", "waiting_confirmation", "waiting_approval"}:
        _require(job is None and expected_phases == [])
        return "not_confirmed"
    _require(type(expected_phases) is list and 1 <= len(expected_phases) <= 16
        and all(type(item) is dict and set(item) == {"phase", "claim_id"} for item in expected_phases)
        and len({item["phase"] for item in expected_phases}) == len(expected_phases)
        and len({item["claim_id"] for item in expected_phases}) == len(expected_phases))
    _require([item["phase"] for item in expected_phases] == ["setup"] if execution["operation"] == "setup" else
        all(type(item["phase"]) is str and item["phase"].startswith("cleanup:") and item["phase"][8:].strip()
            and len(item["phase"]) <= 136 and not any(ord(char) < 32 or ord(char) == 127 for char in item["phase"])
            for item in expected_phases))
    _require(all(item["claim_id"] == "fixture_" + acceptance_digest(
        [execution["project_id"], execution["attempt_id"], execution["case_id"], item["phase"]]).removeprefix("sha256:")
        for item in expected_phases))
    base = {"schema", "project_id", "invocation_id", "request_digest", "selection", "status", "intent_digest", "phases",
        "cancellation_requested", "cancellation_delivered", *FALSE_AUTHORITIES}
    _require(type(job) is dict and job.get("schema") in {"nasus.http-fixture-job.v1", "nasus.http-fixture-job.v2"})
    preparing = job["schema"] == "nasus.http-fixture-job.v2"
    _require(set(job) == base | ({"preparation_digest", "phase", "target_observation_verified"} if preparing else set())
        and job["project_id"] == execution["project_id"] and job["invocation_id"] == execution["invocation_id"]
        and job["request_digest"] == execution["request_digest"] and job["status"] == execution["status"]
        and job["status"] in {"running", "completed", "failed", "cancelled"}
        and job["selection"] == {key: execution[key] for key in ("project_id", "grant_id", "grant_digest", "operation")}
        and all(job[key] is False for key in FALSE_AUTHORITIES)
        and type(job["cancellation_requested"]) is bool and type(job["cancellation_delivered"]) is bool
        and (not job["cancellation_delivered"] or job["cancellation_requested"])
        and job["cancellation_requested"] == (job["status"] == "cancelled")
        and type(job["phases"]) is list)
    if preparing:
        phase = {"running": "preparing", "failed": "preparation_failed", "cancelled": "preparation_cancelled"}
        _require(_digest(job["preparation_digest"]) and job["intent_digest"] is None and job["phases"] == []
            and job["target_observation_verified"] is False and job["phase"] == phase.get(job["status"]))
        return job["phase"]
    _require(_digest(job["intent_digest"]) and len(job["phases"]) == len(expected_phases))
    states = []
    for expected, phase in zip(expected_phases, job["phases"]):
        _require(type(phase) is dict and phase.get("state") in {"not_dispatched", "outcome_unknown", "observed"})
        state = phase["state"]
        _require(set(phase) == {"phase", "claim_id", "state"}
            | ({"dispatch_digest"} if state != "not_dispatched" else set())
            | ({"result_status", "result_digest"} if state == "observed" else set())
            and all(phase[key] == expected[key] for key in ("phase", "claim_id"))
            and (state == "not_dispatched" or _digest(phase["dispatch_digest"]))
            and (state != "observed" or _digest(phase["result_digest"])
                and phase["result_status"] in {"passed", "failed", "error", "timed_out"}))
        states.append(state)
    _require(job["status"] != "completed" or all(state == "observed" for state in states))
    if "outcome_unknown" in states:
        return "outcome_unknown"
    if all(state == "observed" for state in states):
        return "observed"
    return "partially_observed" if "observed" in states else "not_dispatched"
