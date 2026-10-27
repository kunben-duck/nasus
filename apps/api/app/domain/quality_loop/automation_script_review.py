"""Independent review of immutable DSL; no environment or execution approval."""
import json

from .acceptance_specification import acceptance_digest
from .automation_scripts import script_http_protocol


SCRIPT_REVIEW_SCHEMA = "nasus.automation-script-review.v1"
SCRIPT_REVIEW_TOOL = "quality.automation.review"
SCRIPT_REVIEW_QUERY_TOOL = "query.quality.automation_review"
MAX_SCRIPT_REVIEW_BYTES = 64 * 1024 * 1024


class ScriptReviewIntegrityError(ValueError):
    pass


class ScriptReviewChanged(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ScriptReviewIntegrityError(message)


def assess_script_review(proposal, actions, assertions):
    script_http_protocol(proposal)
    _require(proposal.get("status") == "draft"
        and proposal.get("execution_authorized") is False,
        "script review requires an immutable unapproved draft")
    expected_actions, expected_assertions = {}, {}
    for script in proposal["scripts"]:
        case = script["case_id"]
        for index, action in enumerate(script["actions"]):
            expected_actions[(case, index)] = acceptance_digest(action)
        for assertion in script["assertions"]:
            expected_assertions[(case, assertion["row_id"])] = assertion
    observed_actions, observed_assertions = set(), set()
    counts = {decision: 0 for decision in ("accept", "reject", "defer")}
    for item in actions:
        key = (item["case_id"], item["action_index"])
        _require(key in expected_actions and key not in observed_actions
            and type(item["action_index"]) is int and item["action_digest"] == expected_actions[key],
            "review must preserve each exact DSL action once")
        _require(item["decision"] in counts and type(item["reason"]) is str and item["reason"].strip(),
            "every action needs an explicit independent decision and reason")
        counts[item["decision"]] += 1
        observed_actions.add(key)
    for item in assertions:
        key = (item["case_id"], item["row_id"])
        original = expected_assertions.get(key)
        _require(original is not None and key not in observed_assertions
            and type(item["action_index"]) is int and type(item["source_step_index"]) is int
            and all(item[field] == original[field] for field in
                ("action_index", "source_step_index", "oracle_digest")),
            "review must preserve each original oracle/action binding once")
        _require(item["decision"] in counts and type(item["reason"]) is str and item["reason"].strip(),
            "every oracle equivalence needs an explicit decision and reason")
        counts[item["decision"]] += 1
        observed_assertions.add(key)
    _require(observed_actions == set(expected_actions) and observed_assertions == set(expected_assertions),
        "script review cannot omit actions or independent oracle bindings")
    _require(len(json.dumps([actions, assertions], ensure_ascii=False).encode()) <= MAX_SCRIPT_REVIEW_BYTES,
        "complete review exceeds its explicit byte budget; never truncate")
    complete = bool(proposal["scripts"] and not proposal["gaps"] and not counts["reject"] and not counts["defer"])
    return {"review_complete": complete, "reviewed_action_count": len(observed_actions),
        "reviewed_oracle_count": len(observed_assertions), "accepted_count": counts["accept"],
        "rejected_count": counts["reject"], "deferred_count": counts["defer"],
        "gap_count": len(proposal["gaps"]), "automated_count": 0, "executed_on_target_count": 0,
        "passed_count": 0, "execution_authorized": False,
        "remaining_gates": ["target_build_environment_binding", "api_or_dom_locator_evidence",
            "fixture_setup_cleanup", "immutable_run_plan"]}
