from ...domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_ARTIFACT_SCHEMA, MAX_RUN_PLAN_BUILD_BYTES
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class RunPlanBuildArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = RUN_PLAN_BUILD_ARTIFACT_SCHEMA
    namespace = "run-plan-build-bindings"
    MAX_BYTES = MAX_RUN_PLAN_BUILD_BYTES + 2 * 1024 * 1024
