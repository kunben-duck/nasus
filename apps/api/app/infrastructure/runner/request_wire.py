"""One exact wire body shared by transport and persisted observation checks."""
import hashlib
import json

from ...domain.quality_loop.runner_observations import RUNNER_RECEIPT_SCHEMA
from ...domain.quality_loop.http_runner_observations import HTTP_RUNNER_RECEIPT_SCHEMA
from ...domain.quality_loop.http_bindings import HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA, validate_http_binding_steps


def runner_request_body(command):
    if command.kind not in {"browser", "http"}:
        raise ValueError("unsupported runner execution kind")
    if type(command.http_protocol) is not str or command.http_protocol not in {HTTP_RUNNER_RECEIPT_SCHEMA, HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA} or (
            command.kind == "browser" and command.http_protocol != HTTP_RUNNER_RECEIPT_SCHEMA):
        raise ValueError("unsupported runner HTTP protocol")
    if command.http_protocol != HTTP_FIXTURE_RECEIPT_SCHEMA and getattr(command, "fixture_input", None) is not None:
        raise ValueError("fixture resource imports require the explicit v3 protocol")
    payload = {"job_id": command.job_id, "project_id": command.project_id, "us_id": command.us_id,
        "base_url": command.base_url, "steps": list(command.steps), "timeout_ms": command.timeout_ms,
        "metadata": command.metadata, "receipt_protocol": RUNNER_RECEIPT_SCHEMA}
    if command.kind == "http":
        if command.http_protocol == HTTP_FIXTURE_RECEIPT_SCHEMA:
            from .http_fixture_input_verifier import verify_http_fixture_input
            capsule = verify_http_fixture_input(command)
            validate_http_binding_steps(command.steps, fixture_bindings=tuple(item.binding_id for item in capsule.captures))
            payload["fixture_input"] = command.fixture_input
        elif command.http_protocol == HTTP_BINDING_RECEIPT_SCHEMA:
            validate_http_binding_steps(command.steps)
        elif any(isinstance(step, dict) and step.get("action") in {"capture_json", "use_fixture_binding"} for step in command.steps):
            raise ValueError("HTTP response bindings require the explicit v2 protocol")
        payload.update(execution_kind="http", receipt_protocol=command.http_protocol)
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def runner_request_hash(command):
    return "sha256:" + hashlib.sha256(runner_request_body(command)).hexdigest()
