from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts
from ...domain.quality_loop.test_design_mapping import MAPPING_SCHEMA
from ...domain.quality_loop.mapping_part_sets import PARTITIONED_MAPPING_SCHEMA
import json


class TestDesignMappingArtifacts(PinnedRequirementAuthorityArtifacts):
    __test__ = False
    schema = MAPPING_SCHEMA
    schemas = (MAPPING_SCHEMA, PARTITIONED_MAPPING_SCHEMA)
    namespace = "test-design-mapping-reviews"
    MAX_BYTES = 512 * 1024 * 1024
    LEGACY_MAX_BYTES = 8 * 1024 * 1024

    def _legacy_budget(self, payload):
        if payload.get("schema") == MAPPING_SCHEMA and len(json.dumps(payload, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode()) > self.LEGACY_MAX_BYTES:
            raise ValueError("legacy mapping artifact exceeds its unchanged 8 MiB budget")

    def put(self, project_id, payload):
        self._legacy_budget(payload)
        return super().put(project_id, payload)

    def read(self, project_id, ref, digest):
        payload = super().read(project_id, ref, digest)
        self._legacy_budget(payload)
        return payload
