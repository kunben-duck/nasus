from ...domain.quality_loop.test_design_scope import SCOPE_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class TestDesignScopeArtifacts(PinnedRequirementAuthorityArtifacts):
    __test__ = False
    schema = SCOPE_SCHEMA
    namespace = "test-design-scopes"
    MAX_BYTES = 1048576
