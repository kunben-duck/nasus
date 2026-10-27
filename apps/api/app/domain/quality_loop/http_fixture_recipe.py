"""Fixed fixture inputs, never a target execution grant or observation."""
from copy import deepcopy
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .acceptance_specification import acceptance_digest
from .http_fixtures import bind_run_plan_fixture, validate_http_fixture_manifest
from .run_plan import RunPlanIntegrityError
from ..system_image.image_revision import ImageRevisionIntegrityError, require_digest


RECIPE_SCHEMA = "nasus.http-fixture-recipe.v1"
RECIPE_TOOL = "quality.http_fixture.register"
RECIPE_QUERY_TOOL = "query.quality.http_fixture_recipe"
RECIPE_TOOLS = frozenset({RECIPE_TOOL, RECIPE_QUERY_TOOL})
RECIPE_EVENT = "quality.http_fixture.recipe_registered"
RECIPE_PARENT_FIELDS = ("plan_digest", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")
RECIPE_FALSE_AUTHORITIES = ("fixtures_verified", "execution_authorized", "canonical_execution_committed",
    "business_coverage_verified", "baseline_restored")
RECIPE_ZERO_COUNTS = ("automated_count", "executed_on_target_count", "passed_count")
RECIPE_EVENT_FIELDS = ("project_id", "record_id", "run_plan_id", "status")


def recipe_identity(invocation_id):
    return str(uuid5(NAMESPACE_URL, "nasus:http-fixture-recipe:" + invocation_id))


def recipe_metadata(payload):
    try:
        if (type(payload) is not dict or set(payload) != {"schema", "project_id", "record_id", "invocation_id",
                "actor_id", "recorded_at", "request", "parents", "fixture_digest"}
                or payload["schema"] != RECIPE_SCHEMA
                or any(type(payload[key]) is not str or not payload[key].strip() or len(payload[key]) > 128
                    for key in ("project_id", "record_id", "invocation_id", "actor_id"))
                or payload["record_id"] != recipe_identity(payload["invocation_id"])
                or datetime.fromisoformat(payload["recorded_at"]).tzinfo is None
                or type(payload["request"]) is not dict
                or set(payload["request"]) != {"project_id", "run_plan_id", "run_plan_artifact_hash", "manifest"}
                or payload["request"]["project_id"] != payload["project_id"]
                or type(payload["request"]["run_plan_id"]) is not str or not payload["request"]["run_plan_id"].strip()
                or len(payload["request"]["run_plan_id"]) > 128
                or type(payload["parents"]) is not dict or set(payload["parents"]) != set(RECIPE_PARENT_FIELDS)):
            raise RunPlanIntegrityError("fixture recipe original scope invalid")
        manifest = validate_http_fixture_manifest(payload["request"]["manifest"])
        for key in ("plan_digest", "image_artifact_hash", "manifest_hash"):
            require_digest(payload["parents"][key])
        for key in ("image_revision_id", "manifest_id"):
            value = payload["parents"][key]
            if type(value) is not str or not value.strip() or len(value) > 128:
                raise RunPlanIntegrityError("fixture recipe parent identity invalid")
        require_digest(payload["fixture_digest"])
        require_digest(payload["request"]["run_plan_artifact_hash"])
        return {"schema": RECIPE_SCHEMA,
            **{key: payload[key] for key in ("project_id", "record_id", "invocation_id", "actor_id", "recorded_at")},
            **{key: payload["request"][key] for key in ("run_plan_id", "run_plan_artifact_hash")},
            **deepcopy(payload["parents"]), "case_id": manifest["case_id"],
            "data_manifest_hash": acceptance_digest(manifest), "fixture_digest": payload["fixture_digest"],
            "request_hash": acceptance_digest(payload["request"]), "artifact_hash": acceptance_digest(payload),
            "status": "recorded", "historical_not_live": True, "recipe_bytes_verified": True,
            **{key: False for key in RECIPE_FALSE_AUTHORITIES}, **{key: 0 for key in RECIPE_ZERO_COUNTS}}
    except (KeyError, TypeError, AttributeError, ValueError, ImageRevisionIntegrityError) as exc:
        if isinstance(exc, RunPlanIntegrityError):
            raise
        raise RunPlanIntegrityError("fixture recipe original cannot be verified") from exc


def validate_recipe_archive(payload, request, saved):
    metadata = recipe_metadata(payload)
    plan = saved["artifact"]["plan"]
    binding = bind_run_plan_fixture(plan, payload["request"]["manifest"])
    if (payload["request"] != request
            or binding["project_id"] != request["project_id"]
            or saved["metadata"]["project_id"] != request["project_id"]
            or saved["metadata"]["run_plan_id"] != request["run_plan_id"]
            or saved["metadata"]["artifact_hash"] != request["run_plan_artifact_hash"]
            or saved["artifact"]["project_id"] != request["project_id"]
            or saved["artifact"]["run_plan_id"] != request["run_plan_id"]
            or acceptance_digest(saved["artifact"]) != request["run_plan_artifact_hash"]
            or payload["parents"] != {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key]
                for key in RECIPE_PARENT_FIELDS if key != "plan_digest"}}
            or metadata["fixture_digest"] != binding["fixture_digest"]
            or metadata["data_manifest_hash"] != binding["data_manifest_hash"]):
        raise RunPlanIntegrityError("fixture recipe differs from the complete original saved plan")
    return metadata
