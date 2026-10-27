"""Separate an operator policy from the exact originally observed target instance."""
from copy import deepcopy

from .acceptance_specification import acceptance_digest
from .environment_observation_record import environment_record_metadata, validate_environment_envelope
from .http_fixtures import bind_run_plan_fixture
from .run_plan import RunPlanIntegrityError


NATIVE_FIXTURE_ENVIRONMENT_FIELDS = ("record_id", "artifact_hash", "inventory_hash", "operator_policy_digest")


def native_fixture_environment(saved_plan, manifest, environment_view):
    """Readers must authorize the full original plan/build and private inventory first."""
    try:
        archive, metadata = environment_view["archive"], environment_view["metadata"]
        expected = environment_record_metadata(archive)
        observation = validate_environment_envelope(archive)
        plan, parent = saved_plan["artifact"]["plan"], saved_plan["metadata"]
        binding = bind_run_plan_fixture(plan, manifest)
        declaration = plan["selection"]["environment"]
        sources = plan["source_pin"]
        if (acceptance_digest(metadata) != acceptance_digest(expected)
                or environment_view["historical_not_live"] is not True
                or metadata["project_id"] != binding["project_id"]
                or metadata["run_plan_id"] != parent["run_plan_id"]
                or metadata["run_plan_artifact_hash"] != parent["artifact_hash"]
                or metadata["plan_digest"] != plan["plan_digest"]
                or any(metadata[key] != sources[key] for key in ("image_revision_id", "manifest_id"))
                or declaration["kind"] != "local" or declaration["base_url"] != "http://127.0.0.1:8080"
                or metadata["operator_policy_digest"] != declaration["inventory_hash"]
                or metadata["environment_id"] != declaration["environment_id"]
                or metadata["target_artifact_hash"] != plan["selection"]["target_build"]["artifact_hash"]
                or observation.inventory["namespace_origin"] != declaration["base_url"]):
            raise RunPlanIntegrityError("native fixture target differs from its original plan and observed instance")
        return {key: deepcopy(metadata[key]) for key in NATIVE_FIXTURE_ENVIRONMENT_FIELDS}
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, RunPlanIntegrityError):
            raise
        raise RunPlanIntegrityError("original native fixture target cannot be verified") from exc
