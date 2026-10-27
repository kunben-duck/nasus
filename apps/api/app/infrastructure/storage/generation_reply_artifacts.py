from ...application.quality_loop.generation_execution_inputs import GENERATION_REPLY_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class GenerationReplyArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = GENERATION_REPLY_SCHEMA
    namespace = "test-design-native-replies"
    MAX_BYTES = 4 * 1024 * 1024
