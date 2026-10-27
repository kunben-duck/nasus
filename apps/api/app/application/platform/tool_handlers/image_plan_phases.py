import asyncio
from datetime import datetime, timezone

from ...agent.image_plan_phases import ImagePlanPhaseInput
from ..tool_models import ToolResult
from .query_input import query_payload


class ImagePlanPhaseToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            request = ImagePlanPhaseInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            saved = await asyncio.to_thread(self.application.activate, request, invocation_id=invocation.id,
                created_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            await self.events.emit_tool_status(invocation.id, "failed",
                "Plan phase could not be verified. Reload the original goal, revision and source permissions.", [],
                ToolResult(invocation_id=invocation.id, status="failed",
                    summary="Plan phase could not be verified; no execution consent was granted."))
            return
        phase = saved.phase
        await self.events.emit_tool_status(invocation.id, "completed",
            "Original-goal plan phase prepared; the goal remains paused and needs separate execution consent.", [],
            ToolResult(invocation_id=invocation.id, status="completed",
                summary="New fixed-input phase appended. Historical steps, artifacts and authorizations are unchanged.",
                object_refs=[f"build_plan_phase:{phase.phase_id}", f"build_plan:{phase.plan_id}", f"agent_goal:{phase.goal_id}"],
                requires_followup=True, followup_reason="build_plan_phase_prepared",
                followup_prompt="Explicitly resume the original goal, then independently confirm the new execution budget.",
                next_recommended_tools=["query.system_image.build_plans.read"]))
