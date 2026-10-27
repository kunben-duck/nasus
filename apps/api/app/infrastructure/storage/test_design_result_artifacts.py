from ...application.quality_loop.test_design_results import RESULT_SCHEMA, RECOVERED_RESULT_SCHEMA, BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class TestDesignResultArtifacts(PinnedRequirementAuthorityArtifacts):
    __test__ = False
    schema = RESULT_SCHEMA
    schemas = (RESULT_SCHEMA, RECOVERED_RESULT_SCHEMA, BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA)
    namespace = "test-design-results"
    MAX_BYTES = 160 * 1024 * 1024

    def put(self, project_id, payload):
        if payload.get("schema") not in {BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA}:
            import json
            if len(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) > 8 * 1024 * 1024:
                raise ValueError("single-call result exceeds its original 8 MiB budget")
        return super().put(project_id, payload)
