"""Immutable original inventory evidence, not target execution authority."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from uuid import NAMESPACE_URL, uuid5

from .acceptance_specification import acceptance_digest
from .native_environment import NativeEnvironmentObservation
from .run_plan import RunPlanIntegrityError


ENVIRONMENT_RECORD_SCHEMA = "nasus.run-plan-environment-record.v1"
ENVIRONMENT_RECORD_TOOL = "quality.run_plan.record_environment"
ENVIRONMENT_RECORD_QUERY_TOOL = "query.quality.run_plan_environment_record"
ENVIRONMENT_RECORD_TOOLS = frozenset({ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_QUERY_TOOL})
ENVIRONMENT_RECORD_EVENT = "quality.run_plan.environment_recorded"
ENVIRONMENT_EVENT_FIELDS = ("project_id", "record_id", "run_plan_id", "inventory_hash", "status")
FALSE_AUTHORITIES = ("environment_fully_verified", "execution_authorized", "external_egress_denial_verified",
    "host_access_denial_verified", "dependency_health_verified", "fixtures_verified", "locators_verified", "business_coverage_verified")
ZERO_COUNTS = ("automated_count", "executed_on_target_count", "passed_count")
REQUEST_FIELDS = {"project_id", "run_plan_id", "run_plan_artifact_hash", "build_binding_id", "build_binding_artifact_hash"}
PARENT_FIELDS = ("plan_digest", "image_revision_id", "manifest_id", "environment_id", "operator_policy_digest", "target_artifact_hash")


def record_identity(invocation_id):
    return str(uuid5(NAMESPACE_URL, "nasus:run-plan-environment:" + invocation_id))


def validate_record_scope(payload, *, schema, identity):
    expected_fields = {"schema", "project_id", "record_id", "invocation_id", "actor_id", "recorded_at", "request", "parents", "observation"}
    if (type(payload) is not dict or set(payload) != expected_fields or payload["schema"] != schema
            or type(payload["request"]) is not dict or set(payload["request"]) != REQUEST_FIELDS
            or payload["project_id"] != payload["request"]["project_id"]
            or type(payload["parents"]) is not dict or set(payload["parents"]) != set(PARENT_FIELDS)):
        raise RunPlanIntegrityError("environment archive scope differs")
    values = [payload[key] for key in ("project_id", "record_id", "invocation_id", "actor_id")]
    values += [payload["request"][key] for key in ("project_id", "run_plan_id", "build_binding_id")]
    values += [payload["parents"][key] for key in ("image_revision_id", "manifest_id", "environment_id")]
    for value in values:
        if type(value) is not str or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise RunPlanIntegrityError("environment archive identity invalid")
    digests = [payload["request"][key] for key in ("run_plan_artifact_hash", "build_binding_artifact_hash")]
    digests += [payload["parents"][key] for key in ("plan_digest", "operator_policy_digest", "target_artifact_hash")]
    if any(type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in digests):
        raise RunPlanIntegrityError("environment archive requires original SHA-256 pins")
    if payload["record_id"] != identity(payload["invocation_id"]):
        raise RunPlanIntegrityError("environment archive command identity differs")
    try:
        value = payload["recorded_at"]
        if type(value) is not str or len(value) > 64:
            raise ValueError()
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise RunPlanIntegrityError("environment archive requires UTC record time") from None


def validate_environment_envelope(payload):
    validate_record_scope(payload, schema=ENVIRONMENT_RECORD_SCHEMA, identity=record_identity)
    original = payload["observation"]
    if type(original) is not dict or set(original) != {"inventory", "inventory_hash", "observed_at"}:
        raise RunPlanIntegrityError("environment archive lacks exact original observation")
    observation = NativeEnvironmentObservation(deepcopy(original["inventory"]), original["inventory_hash"], original["observed_at"])
    if (observation.inventory["project_id"] != payload["project_id"]
            or any(observation.inventory[key] != payload["parents"][key] for key in ("environment_id", "operator_policy_digest"))
            or observation.inventory["artifact_hash"] != payload["parents"]["target_artifact_hash"]):
        raise RunPlanIntegrityError("environment archive inventory does not belong to its declared parents")
    return observation


def validate_environment_archive(payload, request, plan, binding):
    observation = validate_environment_envelope(payload)
    validate_original_environment_parents(payload, request, plan, binding, observation)
    return observation


def validate_original_environment_parents(payload, request, plan, binding, observation):
    if type(request) is not dict or set(request) != REQUEST_FIELDS or payload["request"] != request:
        raise RunPlanIntegrityError("environment archive original request differs")
    declaration = plan["artifact"]["plan"]["selection"]["environment"]
    metadata, build = plan["metadata"], binding["metadata"]
    expected = {key: metadata[key] for key in ("plan_digest", "image_revision_id", "manifest_id")}
    expected.update(environment_id=declaration["environment_id"], operator_policy_digest=declaration["inventory_hash"],
        target_artifact_hash=build["target_artifact_hash"])
    if (payload["parents"] != expected or metadata["project_id"] != request["project_id"]
            or metadata["run_plan_id"] != request["run_plan_id"] or metadata["artifact_hash"] != request["run_plan_artifact_hash"]
            or build["project_id"] != request["project_id"] or build["binding_id"] != request["build_binding_id"]
            or build["artifact_hash"] != request["build_binding_artifact_hash"]
            or build["run_plan_id"] != request["run_plan_id"] or build["run_plan_artifact_hash"] != request["run_plan_artifact_hash"]
            or any(build[key] != metadata[key] for key in ("plan_digest", "image_revision_id", "manifest_id"))
            or declaration["kind"] != "local" or declaration["base_url"] != "http://127.0.0.1:8080"
            or observation.inventory["project_id"] != request["project_id"]
            or any(observation.inventory[key] != expected[key] for key in ("environment_id", "operator_policy_digest"))
            or observation.inventory["artifact_hash"] != expected["target_artifact_hash"]
            or observation.inventory["namespace_origin"] != declaration["base_url"]):
        raise RunPlanIntegrityError("environment archive original ancestry differs")


def environment_record_metadata(payload):
    validate_environment_envelope(payload)
    original = payload["observation"]
    return {"schema": ENVIRONMENT_RECORD_SCHEMA, **{key: payload[key] for key in
        ("project_id", "record_id", "invocation_id", "actor_id", "recorded_at")},
        **deepcopy(payload["request"]), **deepcopy(payload["parents"]),
        "artifact_hash": acceptance_digest(payload), "request_hash": acceptance_digest(payload["request"]),
        "inventory_hash": original["inventory_hash"], "observed_at": original["observed_at"], "status": "recorded",
        "historical_not_live": True, "native_artifact_attested": True, "isolation_configuration_attested": True,
        "durable_native_observation_verified": True, **{key: False for key in FALSE_AUTHORITIES}, **{key: 0 for key in ZERO_COUNTS}}
