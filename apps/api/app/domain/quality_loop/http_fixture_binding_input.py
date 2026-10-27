"""Versioned fixture resource operands; source hashes alone are not authority."""
import base64
import binascii
from dataclasses import asdict, fields
import hashlib
import json

from .acceptance_specification import acceptance_digest
from .http_bindings import HTTP_BINDING_RECEIPT_SCHEMA, validate_http_binding_steps
from .http_runner_oracles import strict_http_json
from .runner_observations import RunnerObservationInvalid


HTTP_FIXTURE_INPUT_SCHEMA = "nasus.runner-http-fixture-input.v1"
MAX_FIXTURE_SOURCE_BYTES = 256 * 1024
_FIELDS = {"schema", "capture_set", "capture_set_digest", "source_request_body_base64", "source_result_body_base64"}
_JOB_FIELDS = {"job_id", "project_id", "us_id", "base_url", "steps", "timeout_ms", "metadata", "receipt_protocol", "execution_kind"}


def _require(condition):
    if not condition:
        raise RunnerObservationInvalid("original fixture resource input cannot be verified")


def _bytes(value):
    _require(type(value) is str and len(value) <= 4 * ((MAX_FIXTURE_SOURCE_BYTES + 2) // 3))
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise RunnerObservationInvalid("fixture source bytes cannot be decoded") from None
    _require(0 < len(result) <= MAX_FIXTURE_SOURCE_BYTES and base64.b64encode(result).decode("ascii") == value)
    return result


def _object(body):
    try:
        text = body.decode("utf-8", errors="strict")
        # Oracle JSON uses Decimal; protocol DTO integers must retain their JSON types.
        strict_http_json(text)
        result = json.loads(text)
    except UnicodeError:
        raise RunnerObservationInvalid("fixture source is not original UTF-8 JSON") from None
    _require(type(result) is dict)
    return result


def fixture_input_parts(value, *, project_id, case_id, base_url, metadata):
    """Verify immutable pins. Infrastructure must also verify every source artifact."""
    from .run_plan_fixture_captures import CaseFixtureCaptures, FixtureResourceCapture
    try:
        _require(type(value) is dict and set(value) == _FIELDS and value["schema"] == HTTP_FIXTURE_INPUT_SCHEMA)
        raw = value["capture_set"]
        _require(type(raw) is dict and set(raw) == {item.name for item in fields(CaseFixtureCaptures)}
            and type(raw["captures"]) is list)
        capsule = CaseFixtureCaptures(**{**raw, "captures": tuple(FixtureResourceCapture(**item) for item in raw["captures"])})
        _require(capsule.digest == value["capture_set_digest"] and capsule.project_id == project_id and capsule.case_id == case_id
            and type(metadata) is dict and metadata.get("case_id") == case_id and metadata.get("plan_digest") == capsule.plan_digest
            and metadata.get("fixture_capture_digest") == capsule.digest and metadata.get("fixture_scope_digest") == capsule.scope_digest)
        request, result = _bytes(value["source_request_body_base64"]), _bytes(value["source_result_body_base64"])
        _require("sha256:" + hashlib.sha256(request).hexdigest() == capsule.setup_request_hash
            and "sha256:" + hashlib.sha256(result).hexdigest() == capsule.setup_result_hash)
        source, output = _object(request), _object(result)
        _require(set(source) == _JOB_FIELDS and source["execution_kind"] == "http"
            and source["receipt_protocol"] == HTTP_BINDING_RECEIPT_SCHEMA and source["base_url"] == base_url
            and source["project_id"] == project_id and source["us_id"] == case_id
            and type(source["timeout_ms"]) is int and 1000 <= source["timeout_ms"] <= 120000
            and type(source["metadata"]) is dict
            and set(source["metadata"]) == {"fixture_scope", "fixture_phase", "business_coverage_verified"}
            and source["metadata"]["fixture_phase"] == "setup" and source["metadata"]["business_coverage_verified"] is False)
        scope = source["metadata"]["fixture_scope"]
        _require(type(source["steps"]) is list)
        validate_http_binding_steps(tuple(source["steps"]))
        requests, status_assertions = {}, set()
        for index, step in enumerate(source["steps"]):
            if step["action"] == "request":
                _require(step["method"] in {"GET", "HEAD", "POST"})
                if step["method"] == "POST":
                    _require(index + 1 < len(source["steps"]) and source["steps"][index + 1]["action"] == "capture_json"
                        and source["steps"][index + 1]["request_id"] == step["request_id"])
                requests[step["request_id"]] = step
            elif step["action"] == "capture_json":
                _require(requests[step["request_id"]]["method"] == "POST")
            elif step["action"] == "assert_status":
                status_assertions.add(step["request_id"])
        _require(status_assertions == set(requests))
        _require(scope == {"project_id": project_id, "case_id": case_id, "attempt_id": capsule.fixture_attempt_id,
            "parent_digest": capsule.plan_digest, "data_manifest_hash": capsule.data_manifest_hash,
            "environment_id": capsule.environment_id, "artifact_hash": capsule.target_artifact_hash,
            "inventory_hash": capsule.inventory_hash, "timeout_ms": source["timeout_ms"]}
            and type(scope["timeout_ms"]) is int
            and source["job_id"] == "http-fixture-" + acceptance_digest([acceptance_digest(scope), "setup"])[7:]
            and output["runner_job_id"] == source["job_id"] and output["status"] == "passed"
            and output["execution_receipt"]["bindings"] == [asdict(item) for item in capsule.captures])
        return capsule, source, output
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise RunnerObservationInvalid("original fixture resource input cannot be completely verified") from None


def build_fixture_input(capsule, request_body, result_body):
    """Private handoff builder, not a public resource-value or execution grant."""
    _require(type(request_body) is bytes and type(result_body) is bytes
        and 0 < len(request_body) <= MAX_FIXTURE_SOURCE_BYTES and 0 < len(result_body) <= MAX_FIXTURE_SOURCE_BYTES)
    return {"schema": HTTP_FIXTURE_INPUT_SCHEMA, "capture_set": _object(json.dumps(asdict(capsule),
        ensure_ascii=False, allow_nan=False).encode("utf-8")), "capture_set_digest": capsule.digest,
        "source_request_body_base64": base64.b64encode(request_body).decode("ascii"),
        "source_result_body_base64": base64.b64encode(result_body).decode("ascii")}
