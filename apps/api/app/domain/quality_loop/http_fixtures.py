"""Explicit fixture recipes; resource cleanup is not business coverage."""
from copy import deepcopy
import json
import re

from .acceptance_specification import acceptance_digest
from .http_bindings import http_path_bindings, resolve_http_path, validate_http_binding_steps
from .run_plan_observations import verify_plan
from .runner_observations import RunnerObservationInvalid


HTTP_FIXTURE_SCHEMA = "nasus.http-fixture-manifest.v1"
MAX_FIXTURE_BYTES = 128 * 1024


class HttpFixtureInvalid(ValueError):
    pass


def _require(condition):
    if not condition:
        raise HttpFixtureInvalid("HTTP fixture must preserve its complete explicit recipe and resource scope")


def _text(value, limit=2000):
    _require(type(value) is str and bool(value.strip()) and len(value) <= limit
        and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def fixture_bindings(manifest):
    return tuple(step["binding_id"] for step in manifest["setup_steps"] if step["action"] == "capture_json")


def validate_http_fixture_manifest(value):
    try:
        _require(type(value) is dict and set(value) == {"schema", "case_id", "preconditions_digest",
            "setup", "cleanup", "setup_steps", "cleanup_groups"} and value["schema"] == HTTP_FIXTURE_SCHEMA)
        _text(value["case_id"], 128)
        _require(type(value["preconditions_digest"]) is str and
            re.fullmatch(r"sha256:[0-9a-f]{64}", value["preconditions_digest"]) is not None)
        for key in ("setup", "cleanup"):
            _require(type(value[key]) is list and 1 <= len(value[key]) <= 64)
            for item in value[key]:
                _text(item)
        _require(type(value["setup_steps"]) is list)
        steps = tuple(value["setup_steps"])
        validate_http_binding_steps(steps)
        captures = {}
        requests = {}
        assertions = set()
        for index, step in enumerate(steps):
            if step["action"] == "request":
                _require(step["method"] in {"GET", "HEAD", "POST"})
                requests[step["request_id"]] = step
                if step["method"] == "POST":
                    _require(index + 1 < len(steps) and steps[index + 1]["action"] == "capture_json"
                        and steps[index + 1]["request_id"] == step["request_id"])
            elif step["action"] == "capture_json":
                request = requests[step["request_id"]]
                _require(request["method"] == "POST" and step["request_id"] not in captures)
                captures[step["request_id"]] = step["binding_id"]
            elif step["action"] == "assert_status":
                assertions.add(step["request_id"])
        _require(assertions == set(requests) and 1 <= len(captures) <= 16)
        bindings = fixture_bindings(value)
        groups = value["cleanup_groups"]
        _require(type(groups) is dict and set(groups) == set(bindings))
        total = len(steps)
        for binding, group in groups.items():
            _require(type(group) is list and bool(group))
            resolved = []
            cleanup_requests, cleanup_assertions, mutations = set(), set(), 0
            for step in group:
                _require(type(step) is dict and step.get("action") != "capture_json")
                item = deepcopy(step)
                if step.get("action") == "request":
                    _require(http_path_bindings(step["path"]) == [binding])
                    item["path"] = resolve_http_path(step["path"], {binding: "fixture_validation_resource"})
                    cleanup_requests.add(step["request_id"])
                    mutations += step["method"] not in {"GET", "HEAD", "OPTIONS"}
                elif step.get("action") == "assert_status":
                    cleanup_assertions.add(step["request_id"])
                resolved.append(item)
            validate_http_binding_steps(tuple(resolved))
            _require(mutations > 0 and cleanup_assertions == cleanup_requests)
            total += len(group)
        _require(total <= 400 and len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) <= MAX_FIXTURE_BYTES)
    except (RunnerObservationInvalid, KeyError, TypeError, UnicodeError, RecursionError):
        raise HttpFixtureInvalid("HTTP fixture recipe cannot be completely verified") from None
    return deepcopy(value)


def resolve_fixture_cleanup(manifest, binding, resource):
    manifest = validate_http_fixture_manifest(manifest)
    _require(binding in manifest["cleanup_groups"])
    steps = deepcopy(manifest["cleanup_groups"][binding])
    for step in steps:
        if step["action"] == "request":
            step["path"] = resolve_http_path(step["path"], {binding: resource})
    validate_http_binding_steps(tuple(steps))
    return tuple(steps)


def bind_run_plan_fixture(plan, manifest):
    """Validate the original declaration without updating its hash or oracle."""
    plan = verify_plan(plan)
    manifest = validate_http_fixture_manifest(manifest)
    declarations = [item for item in plan["selection"]["fixtures"] if item["case_id"] == manifest["case_id"]]
    _require(len(declarations) == 1)
    declaration = declarations[0]
    _require(declaration["data_manifest_hash"] == acceptance_digest(manifest)
        and all(declaration[key] == manifest[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")))
    return {"project_id": plan["project_id"], "plan_digest": plan["plan_digest"],
        "fixture_digest": acceptance_digest(declaration), "data_manifest_hash": acceptance_digest(manifest)}
