from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .models import ToolInvocation, ToolResult

if TYPE_CHECKING:
    from .store import ApplicationStore


class QueryToolHandler:
    """Executes read-model insight tools through the common ToolInvocation path."""

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def handle(self, invocation: ToolInvocation) -> None:
        conversation = self.store.conversations.get(invocation.conversation_id or "")
        project_id = str(invocation.input_payload.get("project_id") or (conversation.project_id if conversation else "") or "")
        version_id = str(invocation.input_payload.get("version_id") or (conversation.version_id if conversation else "") or "")
        us_id = str(invocation.input_payload.get("us_id") or (conversation.us_id if conversation else "") or "")

        fallback_text = "I reviewed the current workspace state and prepared a concise summary."
        query_keys: list[list[str]] = [["conversation", invocation.conversation_id]] if invocation.conversation_id else []

        if invocation.tool_id == "query.dashboard.progress":
            fallback_text = self.store._build_dashboard_summary("")
            query_keys.extend([["dashboard"], ["welcome"]])
        elif invocation.tool_id == "query.project.status" and project_id:
            fallback_text = self.store._project_status_summary(project_id)
            query_keys.extend([["project", project_id], ["dashboard"]])
        elif invocation.tool_id == "query.version.status" and project_id and version_id:
            fallback_text = self.store._version_status_summary(project_id, version_id)
            query_keys.extend([["project", project_id], ["version", version_id]])
        elif invocation.tool_id == "query.workspace.status" and us_id:
            fallback_text = self.store._workspace_status_summary(us_id)
            if project_id:
                query_keys.append(["workspace", project_id, us_id])
        elif invocation.tool_id == "query.knowledge.status" and project_id:
            fallback_text = self.store._knowledge_status_summary(project_id)
            query_keys.extend([["knowledge", project_id], ["project", project_id]])
        elif invocation.tool_id == "query.system_image.status" and project_id:
            fallback_text = self.store._system_image_status_summary(project_id)
            query_keys.extend([["system-image", project_id], ["knowledge", project_id], ["project", project_id]])
        elif invocation.tool_id == "query.run.status" and project_id:
            fallback_text = self.store._run_status_summary(project_id)
            query_keys.extend([["runs", project_id], ["project", project_id]])
        elif invocation.tool_id == "query.governance.status" and project_id:
            fallback_text = self.store._governance_status_summary(project_id)
            query_keys.extend([["governance", project_id], ["project", project_id]])

        effective_query_keys = query_keys or (
            [["conversation", invocation.conversation_id]] if invocation.conversation_id else []
        )
        await self.store._emit_tool_status(
            invocation.id,
            "running",
            f"Querying {invocation.tool_id}",
            effective_query_keys,
        )
        await asyncio.sleep(0.05)

        content = fallback_text
        metadata: dict[str, Any] = {"planner_kind": "tool_query", "tool_id": invocation.tool_id}
        if conversation:
            llm_update = await self.store._generate_llm_content(
                conversation=conversation,
                user_message=f"Summarize the current state for {invocation.tool_id}.",
                fallback_text=fallback_text,
                system_prompt=(
                    "You are Nasus Agent. Summarize the current domain state concisely "
                    "and recommend the next best action."
                ),
            )
            content = llm_update["content"]
            metadata = {**metadata, **llm_update["metadata"]}

        if invocation.conversation_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                content,
                metadata=metadata,
            )

        await self.store._emit_tool_status(
            invocation.id,
            "completed",
            f"Completed {invocation.tool_id}",
            effective_query_keys,
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=fallback_text,
                object_refs=[f"project:{project_id}"] if project_id else [],
                next_recommended_tools=["quality.scenario.generate"] if invocation.tool_id == "query.workspace.status" else [],
            ),
        )
