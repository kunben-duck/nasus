import asyncio
import logging

from ...quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from ...quality_loop.http_fixture_jobs import HttpFixtureJobTarget
from ...quality_loop.http_fixture_history import HttpFixtureHistoryQuery, HttpFixtureHistoryTarget
from ....domain.quality_loop.http_fixture_history import FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL
from ....domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_QUERY_TOOL
from ....domain.quality_loop.http_fixture_observation import FIXTURE_OBSERVATION_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


logger = logging.getLogger(__name__)


class HttpFixtureJobToolHandler:
    def __init__(self, jobs, events, access):
        self.jobs, self.events, self.access = jobs, events, access

    async def handle(self, invocation):
        if invocation.tool_id == FIXTURE_COMMAND_TOOL:
            await self._dispatch(invocation)
            return
        await self.events.emit_tool_status(invocation.id, "running", "Verifying the original fixture command and source permissions", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            receipt = None
            history = None
            observation = None
            if invocation.tool_id == FIXTURE_OBSERVATION_TOOL:
                target = HttpFixtureHistoryTarget.model_validate(value)
                observation = (await asyncio.to_thread(self.jobs.observations.read, target)).model_dump(mode="json")
                summary = "Original persisted fixture journal inspected; unknown effects are not resent and no coverage or execution permission is granted."
            elif invocation.tool_id in {FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL}:
                target = (HttpFixtureHistoryQuery if invocation.tool_id == FIXTURE_HISTORY_LIST_TOOL
                    else HttpFixtureHistoryTarget).model_validate(value)
                read = self.jobs.history.list if invocation.tool_id == FIXTURE_HISTORY_LIST_TOOL else self.jobs.history.read
                history = (await asyncio.to_thread(read, target)).model_dump(mode="json")
                summary = "Original fixture command metadata inspected; no target observation, execution permission or retry."
            elif invocation.tool_id == FIXTURE_QUERY_TOOL:
                target = HttpFixtureJobTarget.model_validate(value)
                receipt = await asyncio.to_thread(self.jobs.read, target)
                summary = "Original fixture observations inspected; no verified business coverage or baseline restoration."
            else:
                target = HttpFixtureJobTarget.model_validate(value)
                await self.jobs.cancel(target, control_id=invocation.id)
                summary = "Original fixture cancellation inspected or recorded; committed output and unknown effects are retained."
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", summary=summary,
                http_fixture_job=receipt, http_fixture_history=history, http_fixture_observation=observation)
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Fixture lifecycle unavailable. Verify the original grant, administrator/source access and confirmation. Unknown effects are never resent.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)

    async def _dispatch(self, invocation):
        # The runtime has already claimed running durably. Neither a status
        # notification nor a generic error write may reopen a terminal job.
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            request = HttpFixtureExecutionSelection.model_validate(value)
            await self.jobs.dispatch(request, invocation.id)
        except (ValueError, KeyError, PermissionError):
            try:
                await self.jobs.fail(invocation.id)
            except Exception:
                logger.warning("Original fixture termination deferred until its command can be verified and fenced")
        except Exception:
            # Keep the original command for same-ID reconciliation when a
            # preparation or Temporal acknowledgement cannot be determined.
            logger.warning("Original fixture dispatch acknowledgement deferred")
