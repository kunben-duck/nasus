"""Recheck each original response byte before accepting private runner artifacts."""
import base64
import binascii
import hashlib
import json

from ...domain.quality_loop.runner_observations import RunnerObservationInvalid
from ...domain.quality_loop.http_runner_oracles import same_http_json, verify_http_assertion_results
from ...domain.quality_loop.http_bindings import HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA, verify_http_binding_responses


def _decode(item, media_type, byte_limit):
    encoded = item.get("content_base64")
    if (item.get("artifact_type") != "report" or item.get("media_type") != media_type
            or type(encoded) is not str or len(encoded) > 4 * ((byte_limit + 2) // 3)):
        raise RunnerObservationInvalid("HTTP response artifact is invalid or oversized")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise RunnerObservationInvalid("HTTP response encoding is invalid") from None
    if len(body) > byte_limit:
        raise RunnerObservationInvalid("HTTP response artifact exceeds its byte bound")
    return body


def _json(body):
    def distinct(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RunnerObservationInvalid("HTTP observation metadata is ambiguous")
            result[key] = value
        return result
    def invalid(_value):
        raise ValueError()
    try:
        return json.loads(body.decode('utf-8', errors='strict'), object_pairs_hook=distinct,
            parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise RunnerObservationInvalid("HTTP observation metadata cannot be decoded") from None


def verify_http_response_artifacts(receipt, artifacts, steps):
    if type(artifacts) is not list:
        raise RunnerObservationInvalid("HTTP response artifacts are missing")
    by_name = {}
    for item in artifacts:
        if type(item) is not dict or type(item.get("name")) is not str or item["name"] in by_name:
            raise RunnerObservationInvalid("HTTP artifact identities are ambiguous")
        by_name[item["name"]] = item
    expected = {"http-execution.json"} | {"http-response-" + request["request_id"] + suffix
        for request in receipt["requests"] for suffix in (".bin", ".json")}
    if set(by_name) != expected:
        raise RunnerObservationInvalid("HTTP response artifact scope is incomplete")
    if not same_http_json(_json(_decode(by_name['http-execution.json'], 'application/json', 128 * 1024)), receipt):
        raise RunnerObservationInvalid("HTTP manifest differs from the execution receipt")
    responses = {}
    for request in receipt["requests"]:
        item = by_name["http-response-" + request["request_id"] + ".bin"]
        body = _decode(item, 'application/octet-stream', request['response_byte_count'])
        if (len(body) != request["response_byte_count"]
                or "sha256:" + hashlib.sha256(body).hexdigest() != request["response_hash"]):
            raise RunnerObservationInvalid("HTTP response bytes differ from the original observation")
        wire = _decode(by_name['http-response-' + request['request_id'] + '.json'], 'application/json', 96 * 1024)
        if 'sha256:' + hashlib.sha256(wire).hexdigest() != request['response_metadata_hash']:
            raise RunnerObservationInvalid("HTTP response metadata differs from the original observation")
        metadata = _json(wire)
        original = {key: value for key, value in request.items() if key != 'response_metadata_hash'}
        if (type(metadata) is not dict or set(metadata) != set(original) | {'schema', 'headers'}
                or metadata['schema'] != ('nasus.http-response.v2' if receipt['schema'] in {HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA} else 'nasus.http-response.v1')
                or any(type(metadata[key]) is not type(value) or metadata[key] != value for key, value in original.items())
                or type(metadata['headers']) is not dict
                or any(type(key) is not str or key != key.lower() or not key or len(key) > 128
                    or not (type(value) is str or type(value) is list and all(type(item) is str for item in value))
                    for key, value in metadata['headers'].items())):
            raise RunnerObservationInvalid("HTTP response metadata scope cannot be verified")
        responses[request['request_id']] = dict(status=request['response_status'], headers=metadata['headers'], body=body)
    verify_http_binding_responses(receipt, steps, responses)
    verify_http_assertion_results(receipt, steps, responses)
