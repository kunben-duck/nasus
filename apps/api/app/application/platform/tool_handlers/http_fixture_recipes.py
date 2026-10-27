import asyncio
from datetime import datetime, timezone

from ...quality_loop.environment_observation_records import EnvironmentRecordQuery
from ...quality_loop.http_fixture_recipes import HttpFixtureRecipeRequest
from ....domain.quality_loop.http_fixture_recipe import RECIPE_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class HttpFixtureRecipeToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying fixed fixture definition and original RunPlan", [])
        payload = {}
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == RECIPE_TOOL:
                metadata = await asyncio.to_thread(self.application.record, HttpFixtureRecipeRequest.model_validate(payload),
                    invocation_id=invocation.id, recorded_at=datetime.now(timezone.utc).isoformat())
                receipt = {"metadata": metadata, "historical_not_live": True}
            else:
                query = EnvironmentRecordQuery.model_validate(payload)
                receipt = await asyncio.to_thread(self.application.receipt, query.project_id, query.record_id)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", http_fixture_recipe=receipt,
                object_refs=["http_fixture_recipe:" + receipt["metadata"]["record_id"]],
                summary="Complete fixture definition independently registered. No target dispatch, execution grant or verified coverage.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Original fixture definition unavailable. Verify saved plan, private storage, source access and independent confirmation. No target execution recorded.")
        keys = [["http-fixture-recipes", payload["project_id"]]] if result.status == "completed" and invocation.tool_id == RECIPE_TOOL else []
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, keys, result)
