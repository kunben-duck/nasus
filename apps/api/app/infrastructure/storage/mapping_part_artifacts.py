from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts
from ...application.quality_loop.mapping_part_inputs import STAGED_PART_SCHEMA


class MappingPartArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = STAGED_PART_SCHEMA
    namespace = "test-design-mapping-parts"
    MAX_BYTES = 2 * 1024 * 1024
