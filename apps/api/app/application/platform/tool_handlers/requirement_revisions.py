import asyncio

from ...quality_loop.requirement_revision_models import REVISE_REQUIREMENT, RequirementRevisionInput, RequirementSelection
from ...quality_loop.version_delivery_errors import delivery_error
from ....domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError
from ..tool_models import ToolResult
from .query_input import query_payload


class RequirementRevisionToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload,
                preserve=frozenset({"version_id", "us_id"})).items() if k not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == REVISE_REQUIREMENT:
                request = RequirementRevisionInput.model_validate(payload)
                value = await asyncio.to_thread(self.application.revise, request, invocation_id=invocation.id)
                refs = ["version:" + value.version_id, "us:" + value.us_id, "requirement_revision:" + value.revision_id]
                summary = "Requirement draft revision saved; evaluation and independent approval remain pending."
            else:
                request = RequirementSelection.model_validate(payload)
                value = await asyncio.to_thread(self.application.list, request.project_id, request.version_id)
                refs = ["requirement_revision:" + item.revision_id for item in value.items]
                summary = f"Found {len(value.items)} requirement draft(s) in the selected iteration. None grants generation or release authority."
            self.access.require_invocation_project_scope(invocation)
        except (ValueError, KeyError, PermissionError, ImageArtifactUnavailable, ImageRevisionIntegrityError) as exc:
            error = delivery_error(exc)
            await self.events.emit_tool_status(invocation.id, "failed", error.message, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=error.message, followup_reason=error.code))
            return
        await self.events.emit_tool_status(invocation.id, "completed", summary,
            [["version-requirements", request.project_id, request.version_id], ["project", request.project_id]],
            ToolResult(invocation_id=invocation.id, status="completed", summary=summary, object_refs=refs,
                requires_followup=True, followup_reason="requirement_semantic_review_pending"))
