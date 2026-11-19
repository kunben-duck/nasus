import asyncio

from ...quality_loop.case_revisions import CaseRevisionInput
from ...quality_loop.test_design_results import TestDesignResultIntegrityError
from ..errors import PlatformApplicationError
from ....domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError
from ..tool_models import ToolResult
from .query_input import query_payload


def case_revision_error(error):
    if isinstance(error, PermissionError):
        return PlatformApplicationError("case_revision_forbidden", "Case editing or source access is no longer available.", 403)
    if isinstance(error, ImageArtifactUnavailable):
        return PlatformApplicationError("case_revision_unavailable", "Case revision archive is temporarily unavailable.", 503)
    if isinstance(error, (TestDesignResultIntegrityError, ImageRevisionIntegrityError)):
        return PlatformApplicationError("case_revision_integrity_failed", "Case revision history could not be verified.", 502)
    return PlatformApplicationError("case_revision_invalid", "Case revision could not be saved. Check the current draft, steps and unchanged business expectations.", 400)


class CaseRevisionToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            request = CaseRevisionInput.model_validate({k: v for k, v in query_payload(invocation.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}})
            value = await asyncio.to_thread(self.application.revise, request, invocation_id=invocation.id)
            self.access.require_invocation_project_scope(invocation)
        except (ValueError, KeyError, PermissionError, ImageArtifactUnavailable, ImageRevisionIntegrityError) as exc:
            error = case_revision_error(exc)
            await self.events.emit_tool_status(invocation.id, "failed", error.message, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=error.message, followup_reason=error.code))
            return
        await self.events.emit_tool_status(invocation.id, "completed",
            "Case revision saved; independent review is required again.",
            [["test-design-results", request.project_id], ["test-design-review-drafts", request.project_id]],
            ToolResult(invocation_id=invocation.id, status="completed", summary="Immutable case revision saved.",
                object_refs=["test_design_result:" + value["generation_id"]], requires_followup=True,
                followup_reason="independent_case_review_required"))
