import asyncio

from ...quality_loop.version_delivery_models import AdoptIterationImage
from ...quality_loop.version_delivery_errors import delivery_error
from ....domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError
from ..tool_models import ToolResult
from .query_input import query_payload


class IterationImageToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload,
                preserve=frozenset({"version_id"})).items() if k not in {"confirmed_by_user", "confirmed_at"}}
            request = AdoptIterationImage.model_validate(payload)
            identity = await asyncio.to_thread(self.application.adopt, request, invocation_id=invocation.id)
            self.access.require_invocation_project_scope(invocation)
        except (ValueError, KeyError, PermissionError, ImageArtifactUnavailable, ImageRevisionIntegrityError) as exc:
            error = delivery_error(exc)
            await self.events.emit_tool_status(invocation.id, "failed", error.message, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=error.message, followup_reason=error.code))
            return
        await self.events.emit_tool_status(invocation.id, "completed",
            "Working image adopted; requirements and downstream approvals need review.",
            [["version-delivery", request.project_id, request.version_id], ["version-requirements", request.project_id, request.version_id]],
            ToolResult(invocation_id=invocation.id, status="completed",
                summary="Working image adopted; initial baseline is unchanged.",
                object_refs=["iteration_image_adoption:" + identity], requires_followup=True,
                followup_reason="requirement_review_required"))
