"""Independent original health history; never a live lease or execution consent."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from .acceptance_specification import acceptance_digest
from .environment_observation_record import (
    FALSE_AUTHORITIES, ZERO_COUNTS, validate_record_scope, validate_original_environment_parents,
)
from .native_environment_health import HEALTH_SCHEMA, NativeEnvironmentHealthObservation, healthy
from .run_plan import RunPlanIntegrityError


HEALTH_RECORD_SCHEMA = "nasus.run-plan-health-record.v1"
HEALTH_RECORD_TOOL = "quality.run_plan.record_health"
HEALTH_RECORD_QUERY_TOOL = "query.quality.run_plan_health_record"
HEALTH_RECORD_TOOLS = frozenset({HEALTH_RECORD_TOOL, HEALTH_RECORD_QUERY_TOOL})
HEALTH_RECORD_EVENT = "quality.run_plan.health_recorded"
HEALTH_EVENT_FIELDS = ("project_id", "record_id", "run_plan_id", "health_hash", "status")
HEALTH_FALSE_AUTHORITIES = tuple(key for key in FALSE_AUTHORITIES if key != "dependency_health_verified")


def health_record_identity(invocation_id):
    return str(uuid5(NAMESPACE_URL, "nasus:run-plan-health:" + invocation_id))


def validate_health_envelope(payload):
    validate_record_scope(payload, schema=HEALTH_RECORD_SCHEMA, identity=health_record_identity)
    original = payload["observation"]
    if type(original) is not dict or set(original) != {"schema", "inventory", "inventory_hash", "checks", "observed_at"} or original["schema"] != HEALTH_SCHEMA or type(original["checks"]) is not list:
        raise RunPlanIntegrityError("health archive requires complete original probe bytes")
    observed = NativeEnvironmentHealthObservation(deepcopy(original["inventory"]), original["inventory_hash"],
        tuple(deepcopy(original["checks"])), original["observed_at"])
    if (observed.inventory["project_id"] != payload["project_id"]
            or any(observed.inventory[key] != payload["parents"][key] for key in ("environment_id", "operator_policy_digest"))
            or observed.inventory["artifact_hash"] != payload["parents"]["target_artifact_hash"]):
        raise RunPlanIntegrityError("health archive original instance scope differs")
    return observed


def validate_health_archive(payload, request, plan, binding):
    observed = validate_health_envelope(payload)
    validate_original_environment_parents(payload, request, plan, binding, observed)
    return observed


def health_record_metadata(payload):
    observed = validate_health_envelope(payload)
    return {"schema": HEALTH_RECORD_SCHEMA, **{key: payload[key] for key in
        ("project_id", "record_id", "invocation_id", "actor_id", "recorded_at")},
        **deepcopy(payload["request"]), **deepcopy(payload["parents"]),
        "artifact_hash": acceptance_digest(payload), "request_hash": acceptance_digest(payload["request"]),
        "inventory_hash": observed.inventory_hash, "health_hash": observed.content_hash,
        "observed_at": observed.observed_at, "status": "recorded", "historical_not_live": True,
        "native_artifact_attested": True, "isolation_configuration_attested": True,
        "durable_native_observation_verified": True,
        "dependency_health_verified": observed.dependency_health_verified,
        "target_health_verified": observed.target_health_verified,
        "health_checks": [{**{key: item[key] for key in ("role", "probe", "response_hash", "byte_count")},
            "healthy": healthy(item)} for item in observed.checks],
        **{key: False for key in HEALTH_FALSE_AUTHORITIES}, **{key: 0 for key in ZERO_COUNTS}}
