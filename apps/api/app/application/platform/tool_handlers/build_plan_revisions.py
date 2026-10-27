import asyncio
from datetime import datetime, timezone

from ...system_image.build_plan_revisions import BuildPlanRevisionInput
from ..tool_models import ToolResult
from .query_input import query_payload


class BuildPlanRevisionToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            body = {key: value for key, value in query_payload(invocation.input_payload).items()
                    if key not in {"confirmed_at", "confirmed_by_user"}}
            request = BuildPlanRevisionInput.model_validate(body)
            saved = await asyncio.to_thread(self.application.revise, request, invocation_id=invocation.id,
                                            created_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            await self.events.emit_tool_status(invocation.id, "failed",
                "Plan revision could not be verified. Reload the original goal, source access and parent revision.", [],
                ToolResult(invocation_id=invocation.id, status="failed",
                    summary="Plan revision could not be verified; no new work was authorized."))
            return
        await self.events.emit_tool_status(invocation.id, "completed",
            "Source enrichment proposal saved for the same goal; execution requires separate authorization.", [],
            ToolResult(invocation_id=invocation.id, status="completed",
                summary="Same-goal plan revision saved. Original steps, artifacts and consent are unchanged.",
                object_refs=[f"build_plan_revision:{saved.revision.revision_id}", f"build_plan:{saved.revision.plan_id}"],
                requires_followup=True, followup_reason="build_plan_revision_review",
                followup_prompt="Review the revised proposal; this command does not resume or execute the goal.",
                next_recommended_tools=["query.system_image.build_plans.read"]))
