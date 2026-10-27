import asyncio
from datetime import datetime, timezone

from ....domain.system_image.link_decisions import StaleLinkDecision
from ...system_image.image_membership import ImageMembershipApplicationService, ImageReviewFreezeInput
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort
from .query_input import query_payload


class ImageMembershipToolHandler:
    def __init__(self, application: ImageMembershipApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.events.emit_tool_status(invocation.id, "running", "Freezing exact reviewed assertion membership", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = ImageReviewFreezeInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            saved = await asyncio.to_thread(self.application.freeze, request, invocation_id=invocation.id,
                recorded_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, StaleLinkDecision)
            summary = ("Review changed. Reload and confirm the new decision before freezing." if stale else
                       "Cannot freeze reviewed membership. Verify parent, decision pins, reviewer permission and confirmation.")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary,
                requires_followup=stale, followup_reason="stale_link_decision" if stale else None))
            return
        summary = "New candidate pins reviewed references. Parent, publication and business coverage are unchanged."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            object_refs=[f"image_revision:{saved.image_revision_id}"], next_recommended_tools=["query.system_image.revisions.read"]))
