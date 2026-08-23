from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agent import AgentReplyApplicationService
from .read_models import ReadModelSummaryService
from .read_query_ports import AgentQueryReadPort
from .tool_models import ToolInvocation, ToolResult


@dataclass(frozen=True)
class QueryToolPlan:
    fallback_text: str
    query_keys: list[list[str]]
    user_message: str
    planner_kind: str
    prompt_id: str
    project_id: str
    next_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueryToolAnswer:
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class QueryToolUseCaseResult:
    summary: str
    query_keys: list[list[str]]
    tool_result: ToolResult


class QueryToolApplicationService:
    """Read-model query use cases for tool-native agent answers."""

    def __init__(
        self,
        read_model: AgentQueryReadPort,
        agent_replies: AgentReplyApplicationService,
        summaries: ReadModelSummaryService | None = None,
    ) -> None:
        self._read_model = read_model
        self._summaries = summaries or ReadModelSummaryService(read_model)
        self._agent_replies = agent_replies

    def plan(self, invocation: ToolInvocation) -> QueryToolPlan:
        conversation = self._read_model.get_conversation(invocation.conversation_id or "")
        project_id = str(
            invocation.input_payload.get("project_id") or (conversation.project_id if conversation else "") or ""
        )
        version_id = str(
            invocation.input_payload.get("version_id") or (conversation.version_id if conversation else "") or ""
        )
        us_id = str(invocation.input_payload.get("us_id") or (conversation.us_id if conversation else "") or "")
        versions = self._read_model.list_versions(project_id) if project_id else ()
        if project_id and not version_id and versions:
            version_id = versions[0].id

        fallback_text = "I reviewed the current workspace state and prepared a concise summary."
        query_keys: list[list[str]] = [["conversation", invocation.conversation_id]] if invocation.conversation_id else []
        user_message = f"Summarize the current state for {invocation.tool_id}."
        planner_kind = "tool_query"
        prompt_id = "platform_query_tool_reply"
        next_tools: list[str] = []

        if invocation.tool_id == "query.answer":
            fallback_text = str(invocation.input_payload.get("fallback_text") or fallback_text)
            parsed_query_keys = self._parse_query_keys(invocation.input_payload.get("query_keys"))
            if parsed_query_keys:
                query_keys = parsed_query_keys
            user_message = str(invocation.input_payload.get("user_message") or user_message)
            planner_kind = "direct_answer"
            prompt_id = "agent_conversation_reply"
        elif invocation.tool_id in {"query.dashboard.progress", "progress.get"} and not project_id:
            fallback_text = self._summaries.dashboard_summary("")
            query_keys.extend([["dashboard"], ["welcome"]])
        elif invocation.tool_id in {"query.project.status", "project.status.get", "progress.get"} and project_id:
            fallback_text = self._summaries.project_status_summary(project_id)
            query_keys.extend([["project", project_id], ["dashboard"]])
        elif invocation.tool_id in {"query.version.status", "version.progress.get", "risk.summary.get"} and project_id and version_id:
            fallback_text = self._summaries.version_status_summary(project_id, version_id)
            query_keys.extend([["project", project_id], ["version", version_id]])
        elif invocation.tool_id == "risk.summary.get" and project_id:
            fallback_text = self._summaries.project_status_summary(project_id)
            query_keys.extend([["project", project_id], ["dashboard"]])
        elif invocation.tool_id in {"query.workspace.status", "us.status.get"} and us_id:
            fallback_text = self._summaries.workspace_status_summary(us_id)
            if project_id:
                query_keys.append(["workspace", project_id, us_id])
            next_tools = ["quality.scenario.generate"]
        elif invocation.tool_id == "query.knowledge.status" and project_id:
            fallback_text = self._summaries.knowledge_status_summary(project_id)
            query_keys.extend([["knowledge", project_id], ["project", project_id]])
        elif invocation.tool_id in {"query.system_image.status", "system-image.inspect"} and project_id:
            fallback_text = self._summaries.system_image_status_summary(project_id)
            query_keys.extend([["system-image", project_id], ["knowledge", project_id], ["project", project_id]])
        elif invocation.tool_id in {"query.run.status", "run.progress.get"} and project_id:
            fallback_text = self._summaries.run_status_summary(project_id)
            query_keys.extend([["runs", project_id], ["project", project_id]])
        elif invocation.tool_id in {"query.governance.status", "conflicts.get"} and project_id:
            fallback_text = self._summaries.governance_status_summary(project_id)
            query_keys.extend([["governance", project_id], ["project", project_id]])

        effective_query_keys = query_keys or (
            [["conversation", invocation.conversation_id]] if invocation.conversation_id else []
        )
        return QueryToolPlan(
            fallback_text=fallback_text,
            query_keys=effective_query_keys,
            user_message=user_message,
            planner_kind=planner_kind,
            prompt_id=prompt_id,
            project_id=project_id,
            next_tools=next_tools,
        )

    async def answer(self, invocation: ToolInvocation, plan: QueryToolPlan) -> QueryToolAnswer:
        conversation = self._read_model.get_conversation(invocation.conversation_id or "")
        content = plan.fallback_text
        metadata: dict[str, Any] = {"planner_kind": plan.planner_kind, "tool_id": invocation.tool_id}
        if conversation:
            reply = await self._agent_replies.generate_reply(
                conversation=conversation,
                user_message=plan.user_message,
                fallback_text=plan.fallback_text,
                prompt_id=plan.prompt_id,
                purpose="platform.query_tool_reply",
                tool_invocation_id=invocation.id,
            )
            content = reply.content
            metadata = {**metadata, **reply.metadata}
        return QueryToolAnswer(content=content, metadata=metadata)

    async def persist_answer(self, invocation: ToolInvocation, answer: QueryToolAnswer) -> None:
        if invocation.conversation_id:
            await self._agent_replies.append_assistant_message(
                conversation_id=invocation.conversation_id,
                content=answer.content,
                metadata=answer.metadata,
            )

    def complete(self, invocation: ToolInvocation, plan: QueryToolPlan) -> QueryToolUseCaseResult:
        return QueryToolUseCaseResult(
            summary=f"Completed {invocation.tool_id}",
            query_keys=plan.query_keys,
            tool_result=ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=plan.fallback_text,
                object_refs=[f"project:{plan.project_id}"] if plan.project_id else [],
                next_recommended_tools=plan.next_tools,
            ),
        )

    @staticmethod
    def _parse_query_keys(value: Any) -> list[list[str]]:
        if not isinstance(value, list):
            return []
        return [
            [str(part) for part in key]
            for key in value
            if isinstance(key, list) and all(isinstance(part, (str, int, float)) for part in key)
        ]
