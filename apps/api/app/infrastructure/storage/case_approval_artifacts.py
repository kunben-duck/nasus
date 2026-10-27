from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts
from ...domain.quality_loop.case_approval import CASE_APPROVAL_SCHEMA


class CaseApprovalArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = CASE_APPROVAL_SCHEMA
    namespace = "test-design-case-approvals"
    MAX_BYTES = 256 * 1024
