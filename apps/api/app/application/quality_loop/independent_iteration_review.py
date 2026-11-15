"""Identity separation for the iteration workflow, without rewriting legacy approvals."""
from typing import Protocol

from ...domain.system_image.context_pack import ContextPackIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


class ReviewContextPort(Protocol):
    def review_identity(self, project_id, context_id): ...


class IndependentIterationReview:
    def __init__(self, contexts: ReviewContextPort, results):
        self.contexts, self.results = contexts, results

    def _allows(self, project_id, pin, reviewer_id, author):
        context = self.contexts.review_identity(project_id, pin["context_id"])
        if any(context["metadata"].get(key) != pin.get(key) for key in
               ("context_id", "artifact_hash", "image_revision_id", "image_artifact_hash")):
            raise ContextPackIntegrityError("Independent review context does not match its fixed input")
        if context["context"].get("policy_version") != "nasus.test-design-context.v6":
            return True
        author_id = author()
        return bool(reviewer_id and author_id and reviewer_id != author_id)

    def cases(self, project_id, basis, reviewer_id):
        def author():
            pin = basis["generation_pin"]
            result = self.results.read(project_id, pin["generation_id"])
            if result["metadata"]["artifact_hash"] != pin["artifact_hash"]:
                raise ContextPackIntegrityError("Independent review generation pin mismatch")
            return result["result"]["actor_id"]
        return self._allows(project_id, basis["generation_pin"]["context_pin"], reviewer_id, author)

    def script(self, project_id, draft, reviewer_id):
        return self._allows(project_id, draft["result"]["prepared"]["context_pin"], reviewer_id,
            lambda: draft["result"]["actor_id"])

    @staticmethod
    def require(allowed):
        if not allowed:
            raise SourceAccessDenied("Iteration approval requires a reviewer other than the generation author")
