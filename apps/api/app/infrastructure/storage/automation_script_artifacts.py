from ...application.quality_loop.automation_script_inputs import SCRIPT_REPLY_SCHEMA, SCRIPT_RESULT_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class AutomationNativeReplyArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = SCRIPT_REPLY_SCHEMA
    namespace = "automation-native-replies"
    MAX_BYTES = 4 * 1024 * 1024


class AutomationScriptResultArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = SCRIPT_RESULT_SCHEMA
    namespace = "automation-script-drafts"
    MAX_BYTES = 8 * 1024 * 1024
