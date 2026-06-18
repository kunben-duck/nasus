from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .models import ToolInvocation, ToolResult

if TYPE_CHECKING:
    from .store import ApplicationStore


class ProjectVersionToolHandler:
    """Executes project and version management tools."""

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def create_project(self, invocation: ToolInvocation) -> None:
        project_name = str(invocation.input_payload.get("name") or "New Quality Project")
        await self.store._emit_tool_status(
            invocation.id,
            "running",
            f"Creating project {project_name}",
            [["build"], ["dashboard"], ["welcome"], ["projects"]],
        )
        await asyncio.sleep(0.2)
        project = self.store.create_project(project_name)
        if invocation.conversation_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    f"I created the draft project **{project.name}**. Next we should connect a Git repository, "
                    "import US documents, and confirm whether UX boards or historical quality assets are available "
                    "before initializing the Official System Image."
                ),
            )
        await self.store._emit_tool_status(
            invocation.id,
            "completed",
            f"Created draft project {project.name}",
            [["build"], ["dashboard"], ["welcome"], ["projects"]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=f"Created draft project {project.name}",
                object_refs=[f"project:{project.id}"],
                next_recommended_tools=[
                    "system_image.sources.register",
                    "system_image.baseline.initialize",
                    "version.create",
                ],
            ),
        )

    async def create_version(self, invocation: ToolInvocation) -> None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        version_name = str(invocation.input_payload.get("name") or "New Version")
        if not project_id or project_id not in self.store.projects:
            await self.store._emit_tool_status(
                invocation.id,
                "failed",
                "project_id is required to create a version",
                [["projects"]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary="project_id is required to create a version",
                ),
            )
            return

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            f"Creating version branch {version_name}",
            [["project", project_id], ["dashboard"], ["welcome"]],
        )
        await asyncio.sleep(0.2)
        version = self.store.create_version(project_id, version_name)
        if invocation.conversation_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    f"The version branch **{version.name}** is active. "
                    "US board, risk pulse, and asset pack generation are now available in Version Space."
                ),
            )
        await self.store._emit_tool_status(
            invocation.id,
            "completed",
            f"Created version {version.name}",
            [["project", project_id], ["dashboard"], ["welcome"]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=f"Created version {version.name}",
                object_refs=[f"version:{version.id}"],
                next_recommended_tools=["quality.scenario.generate"],
            ),
        )
