from ...domain.quality_loop.http_locator_record import LOCATOR_RECORD_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class HttpLocatorArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = LOCATOR_RECORD_SCHEMA
    namespace = "run-plan-locators"
    MAX_BYTES = 4 * 1024 * 1024 + 32768
