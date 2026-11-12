from ..quality_loop.requirement_revision_models import REVISE_REQUIREMENT, READ_REQUIREMENTS
from ..quality_loop.version_delivery_errors import delivery_error
from ...domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError


class RequirementRevisionReceiptAccess:
    def __init__(self, delivery):
        self.delivery = delivery

    @staticmethod
    def applies(invocation):
        return invocation.tool_id in {REVISE_REQUIREMENT, READ_REQUIREMENTS}

    def require_access(self, invocation):
        if not self.applies(invocation) or invocation.status != "completed":
            return
        try:
            self.delivery.read(invocation.input_payload["project_id"], invocation.input_payload["version_id"])
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
        return invocation.model_copy(deep=True, update={"input_payload": {
            key: value for key, value in invocation.input_payload.items() if key in {"project_id", "version_id"}}})
