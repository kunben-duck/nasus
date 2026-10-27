import asyncio
from datetime import datetime, timezone

from ....domain.system_image.link_decisions import StaleLinkDecision
from ...system_image.semantic_review import SemanticReviewApplicationService, SemanticReviewInput
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort
from .query_input import query_payload


class SemanticReviewToolHandler:
    def __init__(self, application: SemanticReviewApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation: ToolInvocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying semantic review and frozen evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = SemanticReviewInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                                                         if key not in {"confirmed_at", "confirmed_by_user"}})
            decision = await asyncio.to_thread(self.application.review, request, invocation_id=invocation.id,
                                               recorded_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, StaleLinkDecision)
            summary = ("Semantic review changed. Reload its claim history before confirming again." if stale else
                       "Semantic review failed. Check reviewer access, evidence pins and whether this inference supports acceptance.")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(invocation_id=invocation.id, status="failed",
                summary=summary, requires_followup=stale, followup_reason="stale_semantic_decision" if stale else None))
            return
        summary = "Semantic review recorded. Source authority, verified coverage and frozen image membership are unchanged."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(invocation_id=invocation.id,
            status="completed", summary=summary, object_refs=[f"semantic_link_decision:{decision.decision_id}"],
            next_recommended_tools=["query.system_image.links.semantic_decisions"]))
