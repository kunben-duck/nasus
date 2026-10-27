"""Opaque query evidence has no authority over canonical code identities."""
from dataclasses import dataclass
import json


NATIVE_QUERY_BASIS = "decoded_query_response_not_complete_native_graph"
MAX_NATIVE_QUERY_COUNT = 4096
MAX_NATIVE_QUERY_BYTES = 16 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native query JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite native query JSON value")


def native_query_object(value):
    try:
        if type(value) is not str or len(value.encode("utf-8")) > MAX_NATIVE_QUERY_BYTES:
            raise ValueError("native query JSON exceeds size limit")
        parsed = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        if type(parsed) is not dict:
            raise ValueError("native query JSON must be an object")
        json.dumps(parsed, allow_nan=False).encode("utf-8")
    except (TypeError, RecursionError, UnicodeError, OverflowError) as error:
        raise ValueError("invalid native query JSON") from error
    return parsed


@dataclass(frozen=True)
class CodeNativeQueryObservation:
    provider: str
    provider_version: str
    operation: str
    request_json: str
    response_json: str
    basis: str = NATIVE_QUERY_BASIS

    def __post_init__(self):
        for key in ("provider", "provider_version", "operation"):
            value = getattr(self, key)
            if type(value) is not str or not value.strip() or len(value) > 240:
                raise ValueError("invalid native query metadata")
        if self.basis != NATIVE_QUERY_BASIS:
            raise ValueError("native query observation cannot claim graph completeness")
        native_query_object(self.request_json)
        native_query_object(self.response_json)


def validate_native_queries(items):
    if type(items) is not list or not 1 <= len(items) <= MAX_NATIVE_QUERY_COUNT:
        raise ValueError("native query count exceeds limit")
    size = 0
    observations = []
    for item in items:
        if type(item) is not dict or set(item) != {"provider", "provider_version", "operation", "request_json", "response_json", "basis"}:
            raise ValueError("invalid native query observation fields")
        observation = CodeNativeQueryObservation(**item)
        size += len(json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > MAX_NATIVE_QUERY_BYTES:
            raise ValueError("native query archive exceeds size limit")
        observations.append(observation)
    return tuple(observations)
