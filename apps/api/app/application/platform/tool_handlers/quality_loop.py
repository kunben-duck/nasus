from __future__ import annotations

import asyncio

from ...agent import AgentReplyApplicationService
from ..tool_invocation_ports import ToolStatusEventPort
from ...quality_loop import QualityLoopApplicationError, QualityLoopApplicationService
from ..tool_models import ToolInvocation, ToolResult


class QualityLoopToolHandler:
    """Executes quality-loop tools through canonical ToolInvocation handlers.

    AgentGoal lifecycle is owned by AgentGraphRuntime. Handlers here only
    materialize domain state and report ToolResult back to the invocation
    runtime, keeping the control flow aligned with the agent-first contract.
    """

    def __init__(
        self,
        quality_loop_app: QualityLoopApplicationService,
        tool_invocations: ToolStatusEventPort,
        agent_replies: AgentReplyApplicationService,
    ) -> None:
        self.quality_loop_app = quality_loop_app
        self.tool_invocations = tool_invocations
        self.agent_replies = agent_replies

    async def generate_scenarios(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="scenarios")

    async def generate_scope(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="scope")

    async def generate_plan(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="verification_plan")

    async def generate_cases(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="cases")

    async def refresh_asset_pack(self, invocation: ToolInvocation) -> None:
        result = self.quality_loop_app.refresh_asset_pack(invocation)
        if result is None:
            await self._fail_missing_us(invocation)
            return
        await self._complete_result(invocation, result)

    async def generate_automation(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="automation")

    async def generate_change_document(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="change_document")

    async def start_run(self, invocation: ToolInvocation) -> None:
        await self._execute_run(invocation, retry=False)

    async def retry_run(self, invocation: ToolInvocation) -> None:
        await self._execute_run(invocation, retry=True)

    async def _execute_run(self, invocation: ToolInvocation, *, retry: bool) -> None:
        scope = self.quality_loop_app.resolve_scope(invocation)
        if scope is None and not retry:
            await self._fail_missing_us(invocation)
            return
        if scope is not None:
            project_id, us_id = scope
            query_keys = self.quality_loop_app.query_keys_for(invocation, project_id, us_id)
        else:
            query_keys = [["conversation", invocation.conversation_id or ""]]
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            (
                "Retrying persisted execution plan through RunOrchestrator"
                if retry
                else "Starting execution run through RunOrchestrator"
            ),
            query_keys,
        )
        try:
            result = (
                self.quality_loop_app.retry_run(invocation)
                if retry
                else self.quality_loop_app.start_run(invocation)
            )
        except QualityLoopApplicationError as exc:
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                exc.summary,
                query_keys,
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=exc.summary,
                    next_recommended_tools=exc.next_tools,
                ),
            )
            return
        if result is None:
            await self._fail_missing_us(invocation)
            return
        await self._complete_result(invocation, result)

    async def analyze_failure(self, invocation: ToolInvocation) -> None:
        await self._complete_failure_step(invocation, propose_healing=False)

    async def propose_healing(self, invocation: ToolInvocation) -> None:
        await self._complete_failure_step(invocation, propose_healing=True)

    async def assess_release(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="release")

    async def get_release_advice(self, invocation: ToolInvocation) -> None:
        result = self.quality_loop_app.get_release_advice(invocation)
        if result is None:
            await self._fail_missing_us(invocation)
            return
        await self._complete_result(invocation, result, append_assistant=True)

    async def _complete_failure_step(self, invocation: ToolInvocation, *, propose_healing: bool) -> None:
        scope = self.quality_loop_app.resolve_failure_scope(invocation)
        if scope is None:
            exc = QualityLoopApplicationError(
                "A failed run is required before failure analysis or healing can continue",
                next_tools=["query.run.status", "automation.generate"],
            )
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                exc.summary,
                [["conversation", invocation.conversation_id or ""]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=exc.summary,
                    next_recommended_tools=exc.next_tools,
                ),
            )
            return

        project_id, us_id, run = scope
        running_query_keys = self.quality_loop_app.query_keys_for(invocation, project_id, us_id)
        running_query_keys.append(["run", project_id, run.id])
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            "Proposing bounded healing action" if propose_healing else "Analyzing failed run evidence",
            running_query_keys,
        )
        await asyncio.sleep(0.05)
        try:
            result = self.quality_loop_app.complete_failure_step(invocation, propose_healing=propose_healing)
        except QualityLoopApplicationError as exc:
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                exc.summary,
                [["conversation", invocation.conversation_id or ""]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=exc.summary,
                    next_recommended_tools=exc.next_tools,
                ),
            )
            return
        await self._complete_result(invocation, result, append_assistant=True)

    async def _complete_quality_step(self, invocation: ToolInvocation, *, step: str) -> None:
        scope = self.quality_loop_app.resolve_scope(invocation)
        if scope is None:
            await self._fail_missing_us(invocation)
            return
        project_id, us_id = scope
        query_keys = self.quality_loop_app.query_keys_for(invocation, project_id, us_id)

        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            self.quality_loop_app.running_summary(step),
            query_keys,
        )
        await asyncio.sleep(0.05)

        try:
            result = await self.quality_loop_app.complete_quality_step(invocation, step=step)
        except QualityLoopApplicationError as exc:
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                exc.summary,
                query_keys,
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=exc.summary,
                    next_recommended_tools=exc.next_tools,
                ),
            )
            return
        if result is None:
            await self._fail_missing_us(invocation)
            return

        await self._complete_result(invocation, result, append_assistant=True)

    async def _complete_result(
        self,
        invocation: ToolInvocation,
        result,
        *,
        append_assistant: bool = False,
    ) -> None:
        if append_assistant:
            await self._append_assistant_message(
                invocation,
                result.assistant_message or result.summary,
                result.assistant_metadata,
            )
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            result.summary,
            result.query_keys,
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=result.summary,
                object_refs=result.object_refs,
                evidence_refs=result.evidence_refs,
                next_recommended_tools=result.next_tools,
            ),
        )

    async def _append_assistant_message(
        self,
        invocation: ToolInvocation,
        content: str,
        metadata: dict,
    ) -> None:
        if not invocation.conversation_id:
            return
        await self.agent_replies.append_assistant_message(
            conversation_id=invocation.conversation_id,
            content=content,
            metadata=metadata,
        )

    async def _fail_missing_us(self, invocation: ToolInvocation) -> None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        await self._append_assistant_message(
            invocation,
            (
                "I need at least one imported US work item before I can start the quality loop. "
                "Build the system image or import US documents first, then I can generate scenarios, cases, automation, and release evidence."
            ),
            {"planner_kind": "quality_loop_blocked", "missing_context": ["us_work_item"]},
        )
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "failed",
            "US work item is required before quality-loop generation",
            [["conversation", invocation.conversation_id or ""], ["project", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="failed",
                summary="US work item is required before quality-loop generation",
                next_recommended_tools=["system_image.context.materialize"],
            ),
        )
