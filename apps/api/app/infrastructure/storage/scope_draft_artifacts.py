from ...application.quality_loop.scope_draft_inputs import SCOPE_DRAFT_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class ScopeDraftArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = SCOPE_DRAFT_SCHEMA
    namespace = "scope-model-drafts"
    MAX_BYTES = 8 * 1024 * 1024
