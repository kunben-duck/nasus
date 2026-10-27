from ...domain.quality_loop.run_plan import RUN_PLAN_ARTIFACT_SCHEMA, RUN_PLAN_BINDING_ARTIFACT_SCHEMA, RUN_PLAN_FIXTURE_ARTIFACT_SCHEMA, MAX_RUN_PLAN_BYTES
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class RunPlanArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = RUN_PLAN_ARTIFACT_SCHEMA
    schemas = (RUN_PLAN_ARTIFACT_SCHEMA, RUN_PLAN_BINDING_ARTIFACT_SCHEMA, RUN_PLAN_FIXTURE_ARTIFACT_SCHEMA)
    namespace = "run-plans"
    MAX_BYTES = MAX_RUN_PLAN_BYTES + 4 * 1024 * 1024
