import asyncio

from ...system_image.build_authorizations import BuildAuthorizationApplicationService, BuildAuthorizationInput
from ..tool_models import ToolResult
from .query_input import query_payload
from .structure_builds import StructureBuildToolHandler


class BuildAuthorizationToolHandler:
    def __init__(self, authorizations: BuildAuthorizationApplicationService, events, access):
        self.authorizations, self.events, self.access = authorizations, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            request = BuildAuthorizationInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            grant = await asyncio.to_thread(self.authorizations.authorize, request, invocation_id=invocation.id)
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            summary = StructureBuildToolHandler.failure_summary(exc)
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Fixed-plan execution consent saved for this goal and target. One deterministic structural attempt is authorized; model calls, semantic investigation and publication are not authorized."
        await self.events.emit_tool_status(invocation.id, "completed", summary,
            [["system-image-build-plans", grant.project_id]], ToolResult(
                invocation_id=invocation.id, status="completed", summary=summary,
                object_refs=[f"build_authorization:{grant.authorization_id}", f"build_plan:{grant.plan_id}"],
                next_recommended_tools=["system_image.build.structure"]))
