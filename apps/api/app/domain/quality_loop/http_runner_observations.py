"""Exact HTTP observations remain separate from target and business authority."""
import hashlib
import json
import re

from .runner_observations import RunnerObservationInvalid, _RECEIPT_FIELDS, _verify_runner_observations
from .http_bindings import (HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA, http_binding_value_hash,
    http_path_bindings, resolve_http_path, validate_http_binding_steps)
from .http_fixture_binding_input import fixture_input_parts
from .acceptance_specification import acceptance_digest


HTTP_RUNNER_RECEIPT_SCHEMA = "nasus.runner-http-execution.v1"
HTTP_ASSERTIONS = frozenset({"assert_status", "assert_json", "assert_header", "assert_body"})
HTTP_ACTIONS = HTTP_ASSERTIONS | {"request"}
HTTP_RESPONSE_BYTES = 1024 * 1024
HTTP_TOTAL_RESPONSE_BYTES = 16 * 1024 * 1024


def http_step_input_hash(step):
    values = [step.get(key) for key in ("method", "path", "headers_json", "body_json")]
    if any(type(value) is not str for value in values):
        raise RunnerObservationInvalid("HTTP request operands cannot be verified")
    body = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


def verify_http_runner_observations(value, *, job_id, project_id, us_id, request_hash, steps, status,
                                    protocol=HTTP_RUNNER_RECEIPT_SCHEMA, fixture_input=None, base_url=None, metadata=None):
    if type(steps) is not tuple or any(type(step) is not dict for step in steps):
        raise RunnerObservationInvalid("HTTP original steps cannot be verified")
    if type(protocol) is not str or protocol not in {HTTP_RUNNER_RECEIPT_SCHEMA, HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA}:
        raise RunnerObservationInvalid("Unsupported HTTP observation protocol")
    with_fixture = protocol == HTTP_FIXTURE_RECEIPT_SCHEMA
    if not with_fixture and fixture_input is not None:
        raise RunnerObservationInvalid("HTTP fixture imports require the explicit v3 protocol")
    capsule = fixture_input_parts(fixture_input, project_id=project_id, case_id=us_id,
        base_url=base_url, metadata=metadata)[0] if with_fixture else None
    fixture_values = {item.binding_id: item.value for item in capsule.captures} if capsule is not None else {}
    with_bindings = with_fixture or protocol == HTTP_BINDING_RECEIPT_SCHEMA
    if with_bindings:
        validate_http_binding_steps(steps, fixture_bindings=tuple(fixture_values))
    result = _verify_runner_observations(value, job_id=job_id, project_id=project_id, us_id=us_id,
        request_hash=request_hash, step_actions=tuple(step.get("action") for step in steps), status=status,
        schema=protocol, actions=HTTP_ACTIONS | ({"capture_json"} if with_bindings else set()) | ({"use_fixture_binding"} if with_fixture else set()), assertions=HTTP_ASSERTIONS,
        fields=_RECEIPT_FIELDS | {"requests"} | ({"bindings"} if with_bindings else set())
            | ({"fixture_input_hash", "fixture_capture_digest", "fixture_bindings"} if with_fixture else set()))
    states = [step["status"] for step in result["steps"]]
    if (status == "failed" and result["failed_assertion_count"] != 1
            or status in {"error", "timed_out"} and ("failed" in states or all(state == "passed" for state in states))):
        raise RunnerObservationInvalid("HTTP outcome differs from the original step observations")
    expected = [(index, step) for index, step in enumerate(steps)
        if step["action"] == "request" and result["steps"][index]["status"] == "passed"]
    observed = result["requests"]
    if type(observed) is not list or len(observed) != len(expected):
        raise RunnerObservationInvalid("HTTP request observations are incomplete")
    bound_values, paths = {}, {}
    imports = {}
    if with_fixture:
        expected_imports = [(i, step) for i, step in enumerate(steps)
            if step["action"] == "use_fixture_binding" and states[i] == "passed"]
        observed_imports = result["fixture_bindings"]
        if (result["fixture_input_hash"] != acceptance_digest(fixture_input)
                or result["fixture_capture_digest"] != capsule.digest
                or type(observed_imports) is not list or len(observed_imports) != len(expected_imports)):
            raise RunnerObservationInvalid("HTTP fixture receipt lost its complete original input")
        for (index, step), item in zip(expected_imports, observed_imports):
            if (type(item) is not dict or set(item) != {"step_index", "binding_id", "capture_digest", "value_hash"}
                    or type(item["step_index"]) is not int or item["step_index"] != index
                    or item["binding_id"] != step["binding_id"] or item["capture_digest"] != capsule.digest
                    or item["value_hash"] != http_binding_value_hash(fixture_values[step["binding_id"]])):
                raise RunnerObservationInvalid("HTTP imported fixture binding differs from its original capture")
            imports[index] = fixture_values[step["binding_id"]]
    if with_bindings:
        captures = [(i, step) for i, step in enumerate(steps)
            if step["action"] == "capture_json" and states[i] == "passed"]
        if type(result["bindings"]) is not list or len(result["bindings"]) != len(captures):
            raise RunnerObservationInvalid("HTTP binding observations are incomplete")
        requests_by_id = {original["request_id"]: item for (_, original), item in zip(expected, observed)
                          if type(item) is dict}
        bindings_by_index = {i: item for (i, _), item in zip(captures, result["bindings"])}
        for index, step in enumerate(steps):
            if states[index] != "passed":
                break
            if step["action"] == "request":
                paths[index] = resolve_http_path(step["path"], bound_values)
            elif step["action"] == "use_fixture_binding":
                bound_values[step["binding_id"]] = imports[index]
            elif step["action"] == "capture_json":
                item, source = bindings_by_index[index], requests_by_id.get(step["request_id"])
                if (type(item) is not dict or set(item) != {"binding_id", "step_index", "request_id", "pointer", "response_hash", "value", "value_hash"}
                        or item["binding_id"] != step["binding_id"] or type(item["step_index"]) is not int or item["step_index"] != index
                        or item["request_id"] != step["request_id"] or item["pointer"] != step["pointer"]
                        or source is None or type(source.get("response_status")) is not int or not 200 <= source["response_status"] < 300
                        or item["response_hash"] != source.get("response_hash")
                        or item["value_hash"] != http_binding_value_hash(item["value"])):
                    raise RunnerObservationInvalid("HTTP binding observation differs from its original input or response")
                bound_values[item["binding_id"]] = item["value"]
    ids, total = set(), 0
    for (index, original), item in zip(expected, observed):
        resolved = {**original, "path": paths[index]} if with_bindings else original
        if (type(item) is not dict or set(item) != {"request_id", "step_index", "method", "input_hash",
                "response_status", "response_byte_count", "response_hash", "response_metadata_hash"} | (
                    {"declared_input_hash", "path", "binding_ids"} if with_bindings else set())
                or type(item["step_index"]) is not int or item["step_index"] != index
                or type(item["request_id"]) is not str or not 1 <= len(item["request_id"]) <= 128
                or not all(character.isalnum() or character in "_-" for character in item["request_id"])
                or item["request_id"] in ids or item["request_id"] != original.get("request_id")
                or type(item["method"]) is not str or item["method"] != original.get("method") or item["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                or item["input_hash"] != http_step_input_hash(resolved)
                or with_bindings and (item["declared_input_hash"] != http_step_input_hash(original)
                    or item["path"] != resolved["path"] or type(item["binding_ids"]) is not list
                    or item["binding_ids"] != http_path_bindings(original["path"]))
                or type(item["response_status"]) is not int or not 100 <= item["response_status"] <= 599
                or type(item["response_byte_count"]) is not int or not 0 <= item["response_byte_count"] <= HTTP_RESPONSE_BYTES
                or any(type(item[key]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", item[key])
                    for key in ("response_hash", "response_metadata_hash"))):
            raise RunnerObservationInvalid("HTTP request observation differs from original input or bounded response")
        ids.add(item["request_id"])
        total += item["response_byte_count"]
    if total > HTTP_TOTAL_RESPONSE_BYTES:
        raise RunnerObservationInvalid("HTTP response observations exceed the complete byte budget")
    return result
