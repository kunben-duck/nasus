import asyncio

from ...quality_loop.environment_observation_records import EnvironmentRecordQuery
from ...quality_loop.http_fixture_grants import HttpFixtureGrantRequest
from ....domain.quality_loop.http_fixture_grant import GRANT_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class HttpFixtureGrantToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying independent fixture operation consent", [])
        payload = {}
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == GRANT_TOOL:
                metadata = await asyncio.to_thread(self.application.issue, HttpFixtureGrantRequest.model_validate(payload),
                    invocation_id=invocation.id)
                receipt = {"metadata": metadata, "historical_not_live": True}
            else:
                query = EnvironmentRecordQuery.model_validate(payload)
                receipt = await asyncio.to_thread(self.application.read, query.project_id, query.record_id)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", http_fixture_grant=receipt,
                object_refs=["http_fixture_grant:" + receipt["metadata"]["record_id"]],
                summary="Independent bounded fixture operation consent recorded. Target, worker and dispatch gates still required; no verified coverage.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Fixture consent unavailable. Verify original definition, current administrator/source access and fresh independent confirmation. No target execution recorded.")
        keys = [["http-fixture-grants", payload["project_id"]]] if result.status == "completed" and invocation.tool_id == GRANT_TOOL else []
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, keys, result)
