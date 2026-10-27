"""Validate draft DSL provenance, not target validity or business coverage."""
from copy import deepcopy
import json
import re
from urllib.parse import urlsplit

from .acceptance_specification import acceptance_digest
from .automation_input import AUTOMATION_INPUT_SCHEMA, AutomationInputInvalid
from .http_bindings import HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA, validate_http_binding_steps
from .http_runner_observations import HTTP_RUNNER_RECEIPT_SCHEMA


SCRIPT_PROPOSAL_SCHEMA = "nasus.automation-script-proposal.v1"
SCRIPT_BINDING_PROPOSAL_SCHEMA = "nasus.automation-script-proposal.v2"
SCRIPT_FIXTURE_PROPOSAL_SCHEMA = "nasus.automation-script-proposal.v3"
ASSERT_ACTIONS = frozenset({"assert_text", "assert_visible", "assert_url", "assert_status", "assert_json", "assert_header", "assert_body"})
ACTION_FIELDS = {
    "goto": {"url"}, "click": {"selector"}, "fill": {"selector", "value"},
    "press": {"selector", "key"}, "assert_text": {"selector", "value"},
    "assert_visible": {"selector"}, "assert_url": {"value"}, "wait_for": {"selector"},
}
HTTP_ACTION_FIELDS = {
    "request": {"request_id", "method", "path", "headers_json", "body_json"},
    "assert_status": {"request_id", "value"}, "assert_json": {"request_id", "pointer", "value_json"},
    "assert_header": {"request_id", "name", "value"}, "assert_body": {"request_id", "value"},
}


def _require(condition, message):
    if not condition:
        raise AutomationInputInvalid(message)


def _relative_path(path):
    parsed = urlsplit(path)
    _require(path.startswith("/") and not path.startswith("//") and not parsed.scheme
        and not parsed.netloc and not parsed.fragment and "\\" not in path,
        "unbound scripts may only use target-relative URLs")


def _json_operand(value):
    def distinct(items):
        result = {}
        for key, item in items:
            _require(key not in result, "ambiguous HTTP JSON operand")
            result[key] = item
        return result
    def invalid_constant(value):
        raise AutomationInputInvalid("HTTP operand must be strict JSON")
    try:
        return json.loads(value, object_pairs_hook=distinct, parse_constant=invalid_constant)
    except (ValueError, TypeError, RecursionError):
        raise AutomationInputInvalid("HTTP operand must be strict bounded JSON") from None


def verify_script_input(prepared):
    _require(isinstance(prepared, dict) and prepared.get("schema") == AUTOMATION_INPUT_SCHEMA
        and prepared.get("purpose") == "automation", "script generation requires a fixed automation input")
    _require(acceptance_digest({key: value for key, value in prepared.items() if key != "input_digest"})
        == prepared.get("input_digest"), "automation input digest mismatch")
    _require(prepared.get("generation_authorized") is False and prepared.get("execution_authorized") is False
        and all(type(prepared.get(key)) is int and prepared[key] == 0
            for key in ("automated_count", "executed_on_target_count", "passed_count")),
        "automation input cannot grant execution or coverage")


def script_http_protocol(proposal):
    _require(type(proposal) is dict, "script protocol requires an object")
    if proposal.get("schema") == SCRIPT_PROPOSAL_SCHEMA and "http_protocol" not in proposal:
        return HTTP_RUNNER_RECEIPT_SCHEMA
    protocols = {SCRIPT_BINDING_PROPOSAL_SCHEMA: HTTP_BINDING_RECEIPT_SCHEMA,
        SCRIPT_FIXTURE_PROPOSAL_SCHEMA: HTTP_FIXTURE_RECEIPT_SCHEMA}
    schema = proposal.get("schema")
    _require(type(schema) is str and schema in protocols
        and proposal.get("http_protocol") == protocols[schema],
        "script protocol must be explicitly versioned")
    return protocols[schema]


def script_fixture_binding_ids(script):
    """Draft declarations only; original setup captures must be resolved before execution."""
    values = tuple(action["binding_id"] for action in script["actions"] if action["action"] == "use_fixture_binding")
    _require(len(values) <= 16
        and all(type(value) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value) for value in values)
        and len(set(values)) == len(values),
        "fixture imports require distinct bounded resource identities")
    return values


def validate_script_proposal(prepared, output, *, http_protocol=HTTP_RUNNER_RECEIPT_SCHEMA):
    verify_script_input(prepared)
    _require(http_protocol in {HTTP_RUNNER_RECEIPT_SCHEMA, HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA}, "unsupported script HTTP protocol")
    bindings_enabled = http_protocol != HTTP_RUNNER_RECEIPT_SCHEMA
    fixture_enabled = http_protocol == HTTP_FIXTURE_RECEIPT_SCHEMA
    _require(output["input_digest"] == prepared["input_digest"], "scripts belong to another automation input")
    cases = {case["case_id"]: case for case in prepared["cases"]}
    accounted, scripted, gaps = set(), [], []
    for script in output["scripts"]:
        ident = script["case_id"]
        _require(ident in cases and ident not in accounted, "each selected case requires exactly one script or gap")
        accounted.add(ident)
        case = cases[ident]
        _require(script["case_digest"] == acceptance_digest(case), "script changed the original reviewed case")
        kind = script["kind"]
        _require(kind in {"browser", "http"}, "script requires an explicit execution kind")
        observed_steps = set()
        requests = set()
        actions = script["actions"]
        http_fields = {**HTTP_ACTION_FIELDS, **({"capture_json": {"request_id", "pointer", "binding_id"}} if bindings_enabled else {})}
        if fixture_enabled:
            http_fields["use_fixture_binding"] = {"binding_id"}
        for action in actions:
            fields = (http_fields if kind == "http" else ACTION_FIELDS).get(action["action"])
            _require(fields is not None and set(action) == fields | {"action", "source_step_indices"}, "unsupported executable action")
            indices = action["source_step_indices"]
            _require(indices and len(indices) == len(set(indices))
                and all(type(index) is int and 0 <= index < len(case["steps"]) for index in indices),
                "script action must refer to exact original steps")
            observed_steps.update(indices)
            for field in fields:
                value = action[field]
                _require(type(value) is str and (value.strip() or action["action"] in {"assert_json", "capture_json"} and field == "pointer") and len(value) <= 4096
                    and not any(ord(char) < 32 for char in value), "action requires bounded explicit operands")
            if action["action"] in {"goto", "assert_url"}:
                path = action["url" if action["action"] == "goto" else "value"]
                _relative_path(path)
            if kind == "http" and action["action"] != "use_fixture_binding":
                request_id = action["request_id"]
                _require(len(request_id) <= 128 and all(char.isalnum() or char in "_-" for char in request_id),
                    "HTTP action requires a bounded request identity")
                if action["action"] == "request":
                    _require(request_id not in requests and action["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"},
                        "HTTP requests need distinct identities and explicit methods")
                    _relative_path(action["path"])
                    headers = _json_operand(action["headers_json"])
                    _require(isinstance(headers, dict) and len(headers) <= 2
                        and all(name in {"Accept", "Content-Type"} and type(value) is str
                            and value.strip() and len(value) <= 256 and not any(ord(char) < 32 for char in value)
                            for name, value in headers.items()),
                        "HTTP draft headers cannot bind credentials, routing, or environment")
                    _json_operand(action["body_json"])
                    requests.add(request_id)
                else:
                    _require(request_id in requests, "HTTP assertion needs its preceding request")
                    if action["action"] == "assert_status":
                        _require(len(action["value"]) == 3 and action["value"].isascii() and action["value"].isdigit()
                            and 100 <= int(action["value"]) <= 599, "HTTP assertion needs an explicit status")
                    elif action["action"] == "assert_json":
                        pointer = action["pointer"]
                        _require(not pointer or pointer.startswith("/"), "JSON assertion requires a JSON pointer")
                        _require(re.search(r"~(?![01])", pointer) is None, "invalid JSON pointer escaping")
                        _json_operand(action["value_json"])
                    elif action["action"] == "assert_header":
                        _require(action["name"].isascii() and all(char.isalnum() or char == "-" for char in action["name"]),
                            "invalid response header name")
        _require(observed_steps == set(range(len(case["steps"]))), "script omitted an original case step")
        if bindings_enabled and kind == "http":
            validate_http_binding_steps(tuple(actions),
                fixture_bindings=script_fixture_binding_ids(script) if fixture_enabled else ())
        expected = {item["row_id"]: item for item in case["assertions"]}
        observed, action_indices = set(), set()
        for binding in script["assertions"]:
            row = binding["row_id"]
            original = expected.get(row)
            index = binding["action_index"]
            _require(original is not None and row not in observed and type(index) is int
                and 0 <= index < len(actions) and index not in action_indices,
                "each original oracle needs a distinct explicit assertion action")
            _require(binding["source_step_index"] == original["step_index"]
                and binding["oracle_digest"] == original["oracle_digest"]
                and binding["oracle"] == original["oracle"], "script rewrote an independently reviewed oracle")
            _require(actions[index]["action"] in ASSERT_ACTIONS
                and original["step_index"] in actions[index]["source_step_indices"],
                "oracle binding is not an assertion for its original step")
            observed.add(row)
            action_indices.add(index)
        _require(observed == set(expected), "script omitted a reviewed oracle")
        _require(action_indices == {index for index, action in enumerate(actions) if action["action"] in ASSERT_ACTIONS},
            "script introduced an assertion with no independent oracle")
        scripted.append(deepcopy(script))
    for gap in output["gaps"]:
        ident = gap["case_id"]
        _require(ident in cases and ident not in accounted, "case gap is duplicate or outside the selection")
        _require(gap["case_digest"] == acceptance_digest(cases[ident]), "gap changed its original case")
        accounted.add(ident)
        gaps.append(deepcopy(gap))
    _require(accounted == set(cases), "generation must account for every selected case without truncation")
    return {"schema": SCRIPT_FIXTURE_PROPOSAL_SCHEMA if fixture_enabled else SCRIPT_BINDING_PROPOSAL_SCHEMA if bindings_enabled else SCRIPT_PROPOSAL_SCHEMA,
        **({"http_protocol": http_protocol} if bindings_enabled else {}), "input_digest": prepared["input_digest"],
        "scripts": sorted(scripted, key=lambda item: item["case_id"]), "gaps": sorted(gaps, key=lambda item: item["case_id"]),
        "case_count": len(cases), "script_count": len(scripted), "gap_count": len(gaps),
        "status": "draft", "review_status": "pending_independent_review",
        "execution_authorized": False, "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
        "remaining_gates": ["independent_script_review", "target_build_environment_binding",
            "api_or_dom_locator_evidence", "fixture_setup_cleanup", "immutable_run_plan"]}
