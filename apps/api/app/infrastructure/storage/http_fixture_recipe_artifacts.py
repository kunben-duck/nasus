"""Complete input recipe in private S3; local fallback is not canonical storage."""
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts
from ...domain.quality_loop.http_fixture_recipe import RECIPE_SCHEMA
from ...domain.quality_loop.run_plan import RunPlanIntegrityError


class HttpFixtureRecipeArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = RECIPE_SCHEMA
    namespace = "http-fixture-recipes"
    MAX_BYTES = 128 * 1024 + 16384

    def _require_s3(self):
        if not self.storage.config.s3_enabled:
            raise RunPlanIntegrityError("fixture recipes require private S3 storage")

    def put(self, project_id, payload):
        self._require_s3()
        return super().put(project_id, payload)

    def read(self, project_id, ref, digest):
        self._require_s3()
        if type(ref) is not str or not ref.startswith("s3://"):
            raise RunPlanIntegrityError("fixture recipe history cannot use local fallback")
        return super().read(project_id, ref, digest)
