from __future__ import annotations

import asyncio

from ..query_tools import QueryToolApplicationService
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation


class QueryToolHandler:
    """Executes read-model insight tools through the common ToolInvocation path."""

    def __init__(
        self,
        query_app: QueryToolApplicationService,
        tool_invocations: ToolStatusEventPort,
    ) -> None:
        self.query_app = query_app
        self.tool_invocations = tool_invocations

    async def handle(self, invocation: ToolInvocation) -> None:
        plan = self.query_app.plan(invocation)
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            f"Querying {invocation.tool_id}",
            plan.query_keys,
        )
        await asyncio.sleep(0.05)

        answer = await self.query_app.answer(invocation, plan)
        await self.query_app.persist_answer(invocation, answer)
        result = self.query_app.complete(invocation, plan)

        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            result.summary,
            result.query_keys,
            result.tool_result,
        )
