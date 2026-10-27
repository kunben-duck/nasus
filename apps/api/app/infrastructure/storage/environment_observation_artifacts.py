from ...domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class EnvironmentObservationArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = ENVIRONMENT_RECORD_SCHEMA
    namespace = "run-plan-environments"
    MAX_BYTES = 128 * 1024
