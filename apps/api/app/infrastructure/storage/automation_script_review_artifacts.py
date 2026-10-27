from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts
from ...domain.quality_loop.automation_script_review import SCRIPT_REVIEW_SCHEMA, MAX_SCRIPT_REVIEW_BYTES


class AutomationScriptReviewArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = SCRIPT_REVIEW_SCHEMA
    namespace = "automation-script-reviews"
    MAX_BYTES = MAX_SCRIPT_REVIEW_BYTES
