from ...application.quality_loop.generation_batch_ledger import BATCH_REPLY_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class GenerationBatchReplyArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = BATCH_REPLY_SCHEMA
    namespace = "test-design-batch-native-replies"
    MAX_BYTES = 4 * 1024 * 1024
