from ...domain.quality_loop.environment_health_record import HEALTH_RECORD_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class EnvironmentHealthArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = HEALTH_RECORD_SCHEMA
    namespace = "run-plan-health"
    MAX_BYTES = 256 * 1024
