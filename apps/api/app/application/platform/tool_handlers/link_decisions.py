import asyncio
from datetime import datetime, timezone

from ....domain.system_image.link_decisions import StaleLinkDecision
from ...system_image.link_decisions import LinkDecisionApplicationService, LinkReviewInput
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort
from .query_input import query_payload


class LinkDecisionToolHandler:
    def __init__(self, application: LinkDecisionApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.events.emit_tool_status(invocation.id, "running", "Verifying reviewer and frozen reference evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = LinkReviewInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            saved = await asyncio.to_thread(self.application.review, request, invocation_id=invocation.id,
                                           recorded_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, StaleLinkDecision)
            summary = ("Review changed. Reload the decision history and submit against the new head." if stale else
                       "Link review failed. Check reviewer permission, confirmation and exact proposal/evidence pins.")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary,
                requires_followup=stale, followup_reason="stale_link_decision" if stale else None))
            return
        summary = "Reference review recorded without changing frozen image membership, business coverage or publication."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            object_refs=[f"image_link_decision:{saved.decision_id}"],
            next_recommended_tools=["query.system_image.links.decisions"]))
