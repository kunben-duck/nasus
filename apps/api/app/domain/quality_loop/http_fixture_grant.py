"""Independent scope consent, not a target observation or a dispatch receipt."""
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from .acceptance_specification import acceptance_digest
from .http_fixture_recipe import RECIPE_ZERO_COUNTS
from .run_plan import RunPlanIntegrityError
from ..system_image.image_revision import ImageRevisionIntegrityError, require_digest


GRANT_SCHEMA = "nasus.http-fixture-grant.v1"
NATIVE_GRANT_SCHEMA = "nasus.http-fixture-grant.v2"
GRANT_TOOL = "quality.http_fixture.authorize"
GRANT_QUERY_TOOL = "query.quality.http_fixture_grant"
GRANT_TOOLS = frozenset({GRANT_TOOL, GRANT_QUERY_TOOL})
GRANT_EVENT = "quality.http_fixture.operation_authorized"
GRANT_EVENT_FIELDS = ("project_id", "record_id", "status")
GRANT_SECONDS = 900
GRANT_REQUEST_FIELDS = ("project_id", "recipe_id", "recipe_artifact_hash", "attempt_id", "operation", "timeout_ms")
NATIVE_GRANT_REQUEST_FIELDS = (*GRANT_REQUEST_FIELDS, "policy_revision", "environment_record_id", "environment_record_artifact_hash")
GRANT_SCOPE_FIELDS = ("project_id", "attempt_id", "case_id", "parent_digest", "data_manifest_hash",
    "environment_id", "artifact_hash", "inventory_hash", "timeout_ms")


def grant_identity(invocation_id):
    return str(uuid5(NAMESPACE_URL, "nasus:http-fixture-grant:" + invocation_id))


def validate_grant_request(value):
    native = type(value) is dict and value.get("policy_revision") == NATIVE_GRANT_SCHEMA
    if type(value) is not dict or set(value) != set(NATIVE_GRANT_REQUEST_FIELDS if native else GRANT_REQUEST_FIELDS):
        raise RunPlanIntegrityError("fixture grant request must have its exact original fields")
    for key in ("project_id", "recipe_id", "attempt_id", *(("environment_record_id",) if native else ())):
        item = value[key]
        if (type(item) is not str or not 1 <= len(item) <= 128 or not item.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in item)):
            raise RunPlanIntegrityError("fixture grant identity invalid")
        item.encode("utf-8", errors="strict")
    try:
        require_digest(value["recipe_artifact_hash"])
        if native:
            require_digest(value["environment_record_artifact_hash"])
    except ImageRevisionIntegrityError as exc:
        raise RunPlanIntegrityError("fixture grant requires the exact original recipe digest") from exc
    if (type(value["operation"]) is not str or value["operation"] not in {"setup", "cleanup"}
            or type(value["timeout_ms"]) is not int or not 1000 <= value["timeout_ms"] <= 120000):
        raise RunPlanIntegrityError("fixture grant requires one bounded independent operation")
    return deepcopy(value)


def grant_metadata(payload):
    try:
        native = type(payload) is dict and payload.get("schema") == NATIVE_GRANT_SCHEMA
        fields = {"schema", "project_id", "record_id", "invocation_id",
            "actor_id", "recorded_at", "expires_at", "request", "scope", "source_scope_digest"}
        if native:
            fields.add("native_environment")
        if (type(payload) is not dict or set(payload) != fields
                or payload["schema"] not in {GRANT_SCHEMA, NATIVE_GRANT_SCHEMA}
                or payload["record_id"] != grant_identity(payload["invocation_id"])):
            raise RunPlanIntegrityError("fixture grant original identity invalid")
        request = validate_grant_request(payload["request"])
        if native != (request.get("policy_revision") == NATIVE_GRANT_SCHEMA):
            raise RunPlanIntegrityError("fixture grant cannot downgrade its explicit native target policy")
        scope = payload["scope"]
        if type(scope) is not dict or set(scope) != set(GRANT_SCOPE_FIELDS):
            raise RunPlanIntegrityError("fixture grant requires the complete original execution scope")
        for key in ("actor_id", "invocation_id", "record_id", "project_id"):
            value = payload[key]
            if (type(value) is not str or not 1 <= len(value) <= 128 or not value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise RunPlanIntegrityError("fixture grant actor or command invalid")
        for key in ("case_id", "environment_id"):
            value = scope[key]
            if (type(value) is not str or not 1 <= len(value) <= 128 or not value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise RunPlanIntegrityError("fixture grant original scope identity invalid")
            value.encode("utf-8", errors="strict")
        for key in ("parent_digest", "data_manifest_hash", "artifact_hash", "inventory_hash"):
            require_digest(scope[key])
        require_digest(payload["source_scope_digest"])
        native_fields = {}
        if native:
            pin = payload["native_environment"]
            if (type(pin) is not dict or set(pin) != {"record_id", "artifact_hash", "inventory_hash", "operator_policy_digest"}
                    or pin["record_id"] != request["environment_record_id"]
                    or pin["artifact_hash"] != request["environment_record_artifact_hash"]
                    or pin["inventory_hash"] != scope["inventory_hash"]):
                raise RunPlanIntegrityError("fixture grant lost its exact original native inventory binding")
            for key in ("artifact_hash", "inventory_hash", "operator_policy_digest"):
                require_digest(pin[key])
            native_fields = {"policy_revision": NATIVE_GRANT_SCHEMA,
                "environment_record_id": request["environment_record_id"],
                "environment_record_artifact_hash": request["environment_record_artifact_hash"],
                "native_environment": deepcopy(pin)}
        if (payload["project_id"] != request["project_id"] or any(scope[key] != request[key]
                for key in ("project_id", "attempt_id", "timeout_ms"))
                or type(scope["timeout_ms"]) is not int):
            raise RunPlanIntegrityError("fixture grant request differs from its scope")
        if any(type(payload[key]) is not str or len(payload[key]) > 64 for key in ("recorded_at", "expires_at")):
            raise RunPlanIntegrityError("fixture grant timestamps exceed their exact bound")
        issued, expires = (datetime.fromisoformat(payload[key]) for key in ("recorded_at", "expires_at"))
        if issued.tzinfo is None or expires.tzinfo is None or expires - issued != timedelta(seconds=GRANT_SECONDS):
            raise RunPlanIntegrityError("fixture grant must retain its exact bounded lifetime")
        return {**native_fields, **{key: deepcopy(payload[key]) for key in ("schema", "project_id", "record_id", "invocation_id",
                "actor_id", "recorded_at", "expires_at", "scope", "source_scope_digest")},
            **{key: request[key] for key in ("recipe_id", "recipe_artifact_hash", "attempt_id", "operation", "timeout_ms")},
            "request_hash": acceptance_digest(request), "scope_digest": acceptance_digest(scope),
            "grant_digest": acceptance_digest(payload), "status": "issued", "historical_not_live": True,
            "scope_permission_recorded": True, "execution_authorized": False, "canonical_execution_committed": False,
            "fixtures_verified": False, "business_coverage_verified": False, "baseline_restored": False,
            **{key: 0 for key in RECIPE_ZERO_COUNTS}}
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError, ImageRevisionIntegrityError) as exc:
        if isinstance(exc, RunPlanIntegrityError):
            raise
        raise RunPlanIntegrityError("original fixture grant cannot be verified") from exc
