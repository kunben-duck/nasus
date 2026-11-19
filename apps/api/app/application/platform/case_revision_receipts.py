from ..quality_loop.case_revisions import REVISE_CASES
from .tool_handlers.case_revisions import case_revision_error
from ...domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError


class CaseRevisionReceiptAccess:
    def __init__(self, results):
        self.results = results

    @staticmethod
    def applies(invocation):
        return invocation.tool_id == REVISE_CASES

    def require_access(self, invocation):
        if not self.applies(invocation):
            return
        try:
            self.results.read(invocation.input_payload["project_id"], invocation.input_payload["generation_id"])
        except (ValueError, KeyError, PermissionError, ImageArtifactUnavailable, ImageRevisionIntegrityError) as exc:
            raise case_revision_error(exc) from exc

    def require_batch_access(self, invocations):
        for invocation in invocations:
            self.require_access(invocation)

    def broadcast_view(self, invocation):
        if not self.applies(invocation):
            return invocation
        return invocation.model_copy(deep=True, update={"input_payload": {
            key: value for key, value in invocation.input_payload.items() if key in {"project_id", "generation_id"}}})
