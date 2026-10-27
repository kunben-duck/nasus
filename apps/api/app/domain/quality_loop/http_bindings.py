"""Resource-location bindings are not expected results or execution authority."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from .http_runner_oracles import _pointer, strict_http_json
from .runner_observations import RunnerObservationInvalid


HTTP_BINDING_RECEIPT_SCHEMA = "nasus.runner-http-execution.v2"
HTTP_FIXTURE_RECEIPT_SCHEMA = "nasus.runner-http-execution.v3"
_BINDING = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_RESOURCE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_FIELDS = {
    "request": {"request_id", "method", "path", "headers_json", "body_json"},
    "capture_json": {"request_id", "pointer", "binding_id"},
    "assert_status": {"request_id", "value"}, "assert_json": {"request_id", "pointer", "value_json"},
    "assert_header": {"request_id", "name", "value"}, "assert_body": {"request_id", "value"},
}


def _text(value, *, empty=False, limit=4096):
    try:
        valid = (type(value) is str and (empty or value.strip()) and len(value.encode("utf-16-le")) <= limit * 2
                 and not any(ord(char) < 32 or ord(char) == 127 for char in value))
    except UnicodeError:
        valid = False
    if not valid:
        raise RunnerObservationInvalid("HTTP binding operands must be bounded explicit text")


def http_path_bindings(path):
    _text(path)
    pathname, _, query = path.partition("?")
    if re.search(r"[{}]", query):
        raise RunnerObservationInvalid("HTTP bindings cannot change query operands")
    result = []
    for segment in pathname.split("/"):
        match = re.fullmatch(r"\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}", segment)
        if match:
            if match[1] not in result:
                result.append(match[1])
        elif re.search(r"[{}]", segment):
            raise RunnerObservationInvalid("HTTP bindings require complete path segments")
    return result


def resolve_http_path(path, bindings):
    for ident in http_path_bindings(path):
        if type(bindings.get(ident)) is not str or not _RESOURCE.fullmatch(bindings[ident]):
            raise RunnerObservationInvalid("HTTP resource binding is unavailable")
    return re.sub(r"\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}", lambda match: bindings[match[1]], path)


def http_binding_value_hash(value):
    if type(value) is not str or not _RESOURCE.fullmatch(value):
        raise RunnerObservationInvalid("HTTP binding requires a bounded resource identity")
    return "sha256:" + hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def validate_http_binding_steps(steps, *, fixture_bindings=()):
    if type(steps) is not tuple or not 1 <= len(steps) <= 100:
        raise RunnerObservationInvalid("HTTP binding steps cannot be verified")
    requests, bindings = set(), set()
    for step in steps:
        if type(step) is dict and step.get("action") == "use_fixture_binding":
            if (not fixture_bindings or set(step) - {"action", "binding_id", "source_step_indices"}
                    or type(step.get("binding_id")) is not str or step["binding_id"] not in fixture_bindings
                    or step["binding_id"] in bindings or len(bindings) >= 32):
                raise RunnerObservationInvalid("HTTP fixture binding requires its exact original source")
            indices = step.get("source_step_indices")
            if "source_step_indices" in step and (type(indices) is not list or not 1 <= len(indices) <= 512
                    or any(type(index) is not int or not 0 <= index < 512 for index in indices)
                    or len(set(indices)) != len(indices)):
                raise RunnerObservationInvalid("Invalid original fixture step indices")
            bindings.add(step["binding_id"])
            continue
        required = _FIELDS.get(step.get("action")) if type(step) is dict and type(step.get("action")) is str else None
        if (required is None or not required.issubset(step)
                or set(step) - required - {"action", "source_step_indices"}):
            raise RunnerObservationInvalid("Unsupported HTTP binding action fields")
        for key in required:
            _text(step[key], empty=key == "pointer")
        ident = step["request_id"]
        if not 1 <= len(ident) <= 128 or not all(char.isalnum() or char in "_-" for char in ident):
            raise RunnerObservationInvalid("Invalid HTTP request identity")
        indices = step.get("source_step_indices")
        if "source_step_indices" in step and (type(indices) is not list or not 1 <= len(indices) <= 512
                or any(type(index) is not int or not 0 <= index < 512 for index in indices)
                or len(set(indices)) != len(indices)):
            raise RunnerObservationInvalid("Invalid original HTTP step indices")
        action = step["action"]
        if action == "request":
            path = step["path"]
            try:
                parsed = urlsplit(path)
            except ValueError:
                raise RunnerObservationInvalid("HTTP request path cannot be verified") from None
            if (ident in requests or step["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                    or not path.startswith("/") or path.startswith("//") or "\\" in path or "#" in path
                    or parsed.scheme or parsed.netloc or any(key not in bindings for key in http_path_bindings(path))):
                raise RunnerObservationInvalid("HTTP request path or identity cannot be verified")
            headers, body = strict_http_json(step["headers_json"]), strict_http_json(step["body_json"])
            if type(headers) is not dict or len(headers) > 2 or set(headers) - {"Accept", "Content-Type"}:
                raise RunnerObservationInvalid("HTTP headers cannot bind credentials or routing")
            for value in headers.values():
                _text(value, limit=256)
            if step["method"] in {"GET", "HEAD"} and body is not None:
                raise RunnerObservationInvalid("GET and HEAD cannot carry fixture bodies")
            requests.add(ident)
        else:
            if ident not in requests:
                raise RunnerObservationInvalid("HTTP observation must refer to a preceding request")
            if action in {"capture_json", "assert_json"}:
                if step["pointer"] and (not step["pointer"].startswith("/") or re.search(r"~(?![01])", step["pointer"])):
                    raise RunnerObservationInvalid("Invalid HTTP JSON pointer")
            if action == "capture_json":
                name = step["binding_id"]
                if not _BINDING.fullmatch(name) or name in bindings or len(bindings) >= 32:
                    raise RunnerObservationInvalid("HTTP bindings require distinct bounded identities")
                bindings.add(name)
            elif action == "assert_json":
                strict_http_json(step["value_json"])
            elif action == "assert_status" and not re.fullmatch(r"[1-5][0-9]{2}", step["value"]):
                raise RunnerObservationInvalid("Invalid HTTP status oracle")
            elif action == "assert_header" and not re.fullmatch(r"[A-Za-z0-9-]{1,128}", step["name"]):
                raise RunnerObservationInvalid("Invalid HTTP response header name")


def verify_http_binding_responses(receipt, steps, responses):
    """Re-extract every successful binding from complete original response bytes."""
    if receipt["schema"] not in {HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA}:
        return
    observed = iter(receipt["bindings"])
    for step, state in zip(steps, receipt["steps"]):
        if step["action"] != "capture_json" or state["status"] != "passed":
            continue
        item = next(observed, None)
        response = responses.get(step["request_id"])
        if item is None or response is None or not 200 <= response["status"] < 300:
            raise RunnerObservationInvalid("HTTP binding lacks its successful original response")
        try:
            value = _pointer(strict_http_json(response["body"].decode("utf-8", errors="strict")), step["pointer"])
        except UnicodeError:
            raise RunnerObservationInvalid("HTTP binding response is not UTF-8") from None
        if (http_binding_value_hash(value) != item["value_hash"] or value != item["value"]
                or "sha256:" + hashlib.sha256(response["body"]).hexdigest() != item["response_hash"]):
            raise RunnerObservationInvalid("HTTP binding differs from its original JSON response")
    if next(observed, None) is not None:
        raise RunnerObservationInvalid("HTTP binding response scope is ambiguous")
