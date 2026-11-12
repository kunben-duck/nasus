from ..quality_loop.version_delivery_errors import delivery_error
from ...domain.quality_loop.version_delivery import VersionDeliveryIntegrityError
from ...domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError


class VersionDeliveryReceiptAccess:
    def __init__(self, delivery):
        self.delivery = delivery

    @staticmethod
    def applies(invocation):
        return invocation.tool_id == "version.create"

    def require_access(self, invocation):
        if not self.applies(invocation) or invocation.result is None or invocation.result.status != "completed":
            return
        project_id = invocation.input_payload.get("project_id")
        receipt = invocation.result.version_delivery
        try:
            bound = bool(invocation.input_payload.get("image_binding"))
            if receipt is not None:
                if project_id and receipt.project_id != project_id:
                    raise VersionDeliveryIntegrityError("Version receipt project mismatch")
                project_id = receipt.project_id
            versions = [ref.split(":", 1)[1] for ref in invocation.result.object_refs if ref.startswith("version:")]
            if bound and (receipt is None or not receipt.enabled or not project_id or versions != [receipt.version_id]):
                raise VersionDeliveryIntegrityError("Version receipt binding is missing")
            if project_id:
                for version_id in versions:
                    current = self.delivery.read(project_id, version_id)
                    if receipt is not None and any(getattr(receipt, key) != getattr(current, key)
                            for key in ("version_id", "baseline", "iteration_image", "code_revisions", "enabled")):
                        raise VersionDeliveryIntegrityError("Version receipt does not match its original binding")
        except (ValueError, KeyError, PermissionError, ImageArtifactUnavailable, ImageRevisionIntegrityError) as exc:
            raise delivery_error(exc) from exc

    def require_batch_access(self, invocations):
        scopes = {}
        for invocation in invocations:
            if self.applies(invocation) and invocation.result and invocation.result.version_delivery:
                project_id = invocation.result.version_delivery.project_id
                scopes.setdefault(project_id, self.delivery.authorization.scope(project_id))
                self.require_access(invocation)
        if scopes:
            try:
                self.delivery.authorization.require_current_many(tuple(scopes.values()))
            except (ValueError, KeyError, PermissionError) as exc:
                raise delivery_error(exc) from exc

    def broadcast_view(self, invocation):
        if not self.applies(invocation):
            return invocation
        result = invocation.result.model_copy(deep=True) if invocation.result else None
        if result is not None:
            result.version_delivery = None
            result.summary = "Version command status: " + invocation.status
        return invocation.model_copy(deep=True, update={"result": result,
            "summary": "Version command status: " + invocation.status,
            "input_payload": {key: value for key, value in invocation.input_payload.items() if key != "image_binding"}})
