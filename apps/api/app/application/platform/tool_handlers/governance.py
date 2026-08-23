from __future__ import annotations

from typing import Callable

from ..governance import (
    GovernanceApplicationError,
    GovernanceApplicationService,
    GovernanceUseCaseResult,
)
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult


class GovernanceToolHandler:
    """Executes governance tools through the canonical ToolInvocation runtime."""

    def __init__(
        self,
        governance_app: GovernanceApplicationService,
        tool_invocations: ToolStatusEventPort,
    ) -> None:
        self.governance_app = governance_app
        self.tool_invocations = tool_invocations

    async def request_approval(self, invocation: ToolInvocation) -> None:
        await self._execute(invocation, self.governance_app.request_approval)

    async def decide_approval(self, invocation: ToolInvocation) -> None:
        await self._execute(invocation, self.governance_app.decide_approval)

    async def merge_resolution(self, invocation: ToolInvocation) -> None:
        await self._execute(invocation, self.governance_app.merge_resolution)

    async def submit_release_decision(self, invocation: ToolInvocation) -> None:
        await self._execute(invocation, self.governance_app.submit_release_decision)

    async def promote_baseline(self, invocation: ToolInvocation) -> None:
        await self._execute(invocation, self.governance_app.promote_baseline)

    async def _execute(
        self,
        invocation: ToolInvocation,
        use_case: Callable[[ToolInvocation], GovernanceUseCaseResult],
    ) -> None:
        try:
            result = use_case(invocation)
        except GovernanceApplicationError as exc:
            await self._fail(invocation, exc.summary)
            return
        await self._complete(invocation, result)

    async def _complete(self, invocation: ToolInvocation, use_case_result: GovernanceUseCaseResult) -> None:
        result = ToolResult(
            invocation_id=invocation.id,
            status="completed",
            summary=use_case_result.summary,
            object_refs=use_case_result.object_refs,
            evidence_refs=use_case_result.evidence_refs,
            next_recommended_tools=use_case_result.next_tools,
        )
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            use_case_result.summary,
            self.governance_app.query_keys_for(invocation),
            result,
        )

    async def _fail(self, invocation: ToolInvocation, summary: str) -> None:
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "failed",
            summary,
            self.governance_app.query_keys_for(invocation),
            ToolResult(invocation_id=invocation.id, status="failed", summary=summary),
        )
