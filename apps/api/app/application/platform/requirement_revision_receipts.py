from ..quality_loop.requirement_revision_models import REVISE_REQUIREMENT, READ_REQUIREMENTS
from ..quality_loop.requirement_review_models import REVIEW_TOOLS, ReviewSelection
from ..quality_loop.version_delivery_errors import delivery_error
from ...domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError


class RequirementRevisionReceiptAccess:
    def __init__(self, delivery, reviews=None):
        self.delivery, self.reviews = delivery, reviews

    @staticmethod
    def applies(invocation):
        return invocation.tool_id in {REVISE_REQUIREMENT, READ_REQUIREMENTS, *REVIEW_TOOLS}

    def require_access(self, invocation):
        if not self.applies(invocation) or invocation.status != "completed":
            return
        try:
            self.delivery.read(invocation.input_payload["project_id"], invocation.input_payload["version_id"])
            if invocation.tool_id in REVIEW_TOOLS:
                if self.reviews is None:
                    raise PermissionError("Requirement review authorization is unavailable")
                self.reviews.read(ReviewSelection(**{key: invocation.input_payload[key] for key in ReviewSelection.model_fields}))
        except (ValueError, KeyError, PermissionError, ImageArtifactUnavailable, ImageRevisionIntegrityError) as exc:
            raise delivery_error(exc) from exc

    def require_batch_access(self, invocations):
        scopes = {}
        for invocation in invocations:
            if self.applies(invocation) and invocation.status == "completed":
                project_id = invocation.input_payload["project_id"]
                scopes.setdefault(project_id, self.delivery.authorization.scope(project_id))
                self.require_access(invocation)
        if scopes:
            self.delivery.authorization.require_current_many(tuple(scopes.values()))

    def broadcast_view(self, invocation):
        if not self.applies(invocation):
            return invocation
        view = invocation.model_copy(deep=True, update={"input_payload": {
            key: value for key, value in invocation.input_payload.items() if key in {"project_id", "version_id"}}})
        if view.result:
            view.result.requirement_review = None
        return view
