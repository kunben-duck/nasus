from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from ...agent import AgentReplyApplicationService
from ..tool_invocation_ports import ToolStatusEventPort
from ...quality_loop import (
    ProjectVersionApplicationError,
    ProjectVersionApplicationService,
    ProjectVersionUseCaseResult,
)
from ..tool_models import ToolInvocation, ToolResult


ProjectVersionUseCase = Callable[[ToolInvocation], ProjectVersionUseCaseResult]
AsyncProjectVersionUseCase = Callable[[ToolInvocation], Awaitable[ProjectVersionUseCaseResult]]


class ProjectVersionToolHandler:
    """Adapts project/version ToolInvocations to application use cases."""

    def __init__(
        self,
        project_version_app: ProjectVersionApplicationService,
        tool_invocations: ToolStatusEventPort,
        agent_replies: AgentReplyApplicationService,
    ) -> None:
        self.project_version_app = project_version_app
        self.tool_invocations = tool_invocations
        self.agent_replies = agent_replies

    async def create_project(self, invocation: ToolInvocation) -> None:
        project_name = str(invocation.input_payload.get("name") or "New Quality Project")
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            f"Creating project {project_name}",
            [["build"], ["dashboard"], ["welcome"], ["projects"]],
        )
        await asyncio.sleep(0.2)
        await self._complete_result(invocation, self.project_version_app.create_project(invocation))

    async def create_version(self, invocation: ToolInvocation) -> None:
        project_id = self.project_version_app.project_id_for(invocation)
        version_name = str(invocation.input_payload.get("name") or "New Version")
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            f"Creating version branch {version_name}",
            [["project", project_id], ["dashboard"], ["welcome"]] if project_id else [["projects"]],
        )
        await asyncio.sleep(0.2)
        await self._run(invocation, self.project_version_app.create_version)

    async def connect_project_assets(self, invocation: ToolInvocation) -> None:
        await self._run(invocation, self.project_version_app.connect_project_assets)

    async def import_version_inputs(self, invocation: ToolInvocation) -> None:
        await self._run(invocation, self.project_version_app.import_version_inputs)

    async def bind_version_branch(self, invocation: ToolInvocation) -> None:
        await self._run(invocation, self.project_version_app.bind_version_branch)

    async def assign_version_participants(self, invocation: ToolInvocation) -> None:
        await self._run(invocation, self.project_version_app.assign_version_participants)

    async def initialize_version_risk(self, invocation: ToolInvocation) -> None:
        await self._run(invocation, self.project_version_app.initialize_version_risk)

    async def start_us_task(self, invocation: ToolInvocation) -> None:
        await self._run_async(invocation, self.project_version_app.start_us_task)

    async def _run(self, invocation: ToolInvocation, use_case: ProjectVersionUseCase) -> None:
        try:
            result = use_case(invocation)
        except ProjectVersionApplicationError as exc:
            await self._fail(invocation, exc.summary)
            return
        await self._complete_result(invocation, result)

    async def _run_async(self, invocation: ToolInvocation, use_case: AsyncProjectVersionUseCase) -> None:
        try:
            result = await use_case(invocation)
        except ProjectVersionApplicationError as exc:
            await self._fail(invocation, exc.summary)
            return
        await self._complete_result(invocation, result)

    async def _complete_result(self, invocation: ToolInvocation, result: ProjectVersionUseCaseResult) -> None:
        if invocation.conversation_id and result.assistant_message:
            await self.agent_replies.append_assistant_message(
                conversation_id=invocation.conversation_id,
                content=result.assistant_message,
                metadata={"planner_kind": "project_version_tool", "tool_id": invocation.tool_id},
            )
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            result.summary,
            self.project_version_app.query_keys_for(invocation),
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=result.summary,
                object_refs=result.object_refs,
                evidence_refs=result.evidence_refs,
                requires_followup=result.requires_followup,
                next_recommended_tools=result.next_tools,
            ),
        )

    async def _fail(self, invocation: ToolInvocation, summary: str) -> None:
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "failed",
            summary,
            self.project_version_app.query_keys_for(invocation),
            ToolResult(invocation_id=invocation.id, status="failed", summary=summary),
        )
