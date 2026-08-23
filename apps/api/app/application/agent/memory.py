from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from .agent_models import (
    AgentGoal,
    AgentMemoryItem,
    AgentMemoryLink,
    ConversationMessage,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from .conversation_summary import ConversationSummaryCheckpointService
from .ports import AgentMemoryStatePort
from .tool_context import compact_tool_catalog_json
from ...domain.agent.memory import AgentMemoryContext, memory_context_hash, memory_context_summary
from ..system_image.memory_context import SystemImageMemoryContextApplicationService
from ..system_image.ports import SystemImageWorkspacePort
from ..platform.tool_models import ToolDefinition
from ..platform.prompts import PromptRegistryPort
from ..system_image.retrieval import SystemImageMemoryHit, SystemImageRetriever
from ...domain.platform.prompt_registry import builtin_prompt


class AgentMemoryManager:
    """Builds the structured context package used before LLM-backed agent calls."""

    def __init__(
        self,
        state: AgentMemoryStatePort,
        system_image_retriever: SystemImageRetriever,
        system_image_workspace: SystemImageWorkspacePort,
        conversation_summaries: ConversationSummaryCheckpointService | None = None,
        prompt_registry: PromptRegistryPort | None = None,
    ) -> None:
        self._state = state
        self.conversation_summaries = (
            conversation_summaries or ConversationSummaryCheckpointService()
        )
        self.system_image_memory_context = SystemImageMemoryContextApplicationService(
            system_image_workspace
        )
        self.system_image_retriever = system_image_retriever
        self._prompt_registry = prompt_registry

    async def get_context_view(
        self,
        *,
        conversation_id: str | None = None,
        agent_goal_id: str | None = None,
        space_ref: str | None = None,
    ) -> dict[str, Any]:
        """Return the API-facing Agent memory view for a conversation scope."""

        conversation = self._conversation_for_memory_query(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )
        goal = (
            self._state.get_goal(agent_goal_id)
            if agent_goal_id
            else self._state.active_goal_for_conversation(conversation.id)
        )
        tools = list(self._state.available_tools())
        memory_context = await self.build_context(conversation, tools=tools)
        latest_checkpoint = self._latest_checkpoint(conversation.id)
        project_id = conversation.project_id

        return {
            "conversation_id": conversation.id,
            "agent_goal_id": goal.id if goal else None,
            "context_hash": memory_context_hash(memory_context),
            "context_summary": memory_context_summary(memory_context),
            "recent_turn_count": memory_context.recent_turn_count,
            "checkpoint_count": memory_context.checkpoint_count,
            "working_memory": self._working_memory_view(goal),
            "conversation_memory": {
                "latest_summary_checkpoint_id": latest_checkpoint.id if latest_checkpoint else None,
                "recent_message_refs": [message.id for message in conversation.messages[-6:]],
                "checkpoint_count": memory_context.checkpoint_count,
                "recent_turn_count": memory_context.recent_turn_count,
            },
            "retrieved_context": {
                "query": memory_context.retrieval_query,
                "refs": memory_context.retrieved_context_refs,
                "summary": memory_context.retrieved_context_summary,
            },
            "project_long_term_memory": self._project_long_term_memory_view(project_id),
            "candidate_memory": self._candidate_memory_view(conversation, project_id),
            "tool_catalog": {
                "tool_count": len(tools),
                "tool_ids": [tool.tool_id for tool in tools],
            },
        }

    async def create_summary_checkpoint(
        self,
        *,
        conversation_id: str | None = None,
        agent_goal_id: str | None = None,
        space_ref: str | None = None,
        created_by: str = "user",
    ) -> ConversationSummaryCheckpoint:
        """Create a durable conversation summary checkpoint for Agent memory."""

        conversation = self._conversation_for_memory_query(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )
        latest_checkpoint = self._latest_checkpoint(conversation.id)
        checkpoint = self._build_summary_checkpoint(conversation, force=True, created_by=created_by)
        if checkpoint is None:
            if latest_checkpoint is not None:
                return latest_checkpoint
            raise ValueError("No completed text messages are available to checkpoint.")
        if latest_checkpoint and latest_checkpoint.message_range_end == checkpoint.message_range_end:
            return latest_checkpoint

        self._state.persist_summary_checkpoint(conversation, checkpoint)
        await self._state.publish_memory_checkpointed(conversation, checkpoint)
        return checkpoint

    def record_item(
        self,
        *,
        memory_scope: str,
        owner_ref: str,
        summary: str,
        source_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        expires_at: str | None = None,
        link_refs: list[tuple[str, str, float]] | None = None,
    ) -> AgentMemoryItem:
        """Persist a reusable Agent memory fact and its traceable graph links."""

        created_at = _now_iso()
        compact_source_refs = list(dict.fromkeys(source_refs or []))[:24]
        compact_object_refs = list(dict.fromkeys(object_refs or []))[:24]
        compact_evidence_refs = list(dict.fromkeys(evidence_refs or []))[:24]
        item = AgentMemoryItem(
            id=f"mem_{uuid4().hex[:10]}",
            memory_scope=memory_scope,  # type: ignore[arg-type]
            owner_ref=owner_ref,
            source_refs=compact_source_refs,
            summary=summary,
            object_refs=compact_object_refs,
            evidence_refs=compact_evidence_refs,
            expires_at=expires_at,
            created_at=created_at,
        )
        self._state.persist_memory_item(item)

        seen_links: set[tuple[str, str]] = set()

        def add_link(target_ref: str, link_kind: str, confidence: float) -> None:
            if not target_ref or (target_ref, link_kind) in seen_links:
                return
            seen_links.add((target_ref, link_kind))
            link = AgentMemoryLink(
                id=f"memlink_{uuid4().hex[:10]}",
                memory_id=item.id,
                target_ref=target_ref,
                link_kind=link_kind,  # type: ignore[arg-type]
                confidence=max(0.0, min(confidence, 1.0)),
                created_at=created_at,
            )
            self._state.persist_memory_link(link)

        add_link(owner_ref, "belongs_to", 1.0)
        for ref in compact_source_refs:
            add_link(ref, "derived_from", 0.9)
        for ref in compact_object_refs:
            add_link(ref, "supports", 0.85)
        for ref in compact_evidence_refs:
            add_link(ref, "evidenced_by", 0.85)
        for target_ref, link_kind, confidence in link_refs or []:
            add_link(target_ref, link_kind, confidence)

        return item

    def list_items(
        self,
        *,
        owner_ref: str | None = None,
        memory_scope: str | None = None,
        status: str | None = None,
        source_ref: str | None = None,
    ) -> list[AgentMemoryItem]:
        items = list(self._state.list_memory_items())
        if owner_ref is not None:
            items = [item for item in items if item.owner_ref == owner_ref]
        if memory_scope is not None:
            items = [item for item in items if item.memory_scope == memory_scope]
        if status is not None:
            items = [item for item in items if item.status == status]
        if source_ref is not None:
            items = [item for item in items if source_ref in item.source_refs]
        return sorted(items, key=lambda item: item.created_at)

    async def build_context(
        self,
        conversation: ConversationSession,
        *,
        tools: list[ToolDefinition] | None = None,
        trace_retrieval: bool = False,
    ) -> AgentMemoryContext:
        history_snapshot = self.history_snapshot(conversation)
        recent_turn_count = len(self._recent_text_messages(conversation)[-6:])
        checkpoint_count = sum(
            1
            for checkpoint in self._state.list_summary_checkpoints()
            if checkpoint.conversation_id == conversation.id
        )
        retrieval_query = self._retrieval_query(conversation)
        memory_search = await self.retrieve_system_image_memory(
            conversation,
            retrieval_query,
            trace=trace_retrieval,
        )
        memory_hits = list(memory_search.hits)
        return AgentMemoryContext(
            system_prompt=self.system_prompt(conversation),
            context_snapshot=self.context_snapshot(conversation, tools=tools, memory_hits=memory_hits),
            history_snapshot=history_snapshot,
            recent_turn_count=recent_turn_count,
            checkpoint_count=checkpoint_count,
            retrieval_query=retrieval_query,
            retrieved_context_refs=[hit.ref for hit in memory_hits],
            retrieved_context_summary=self._retrieved_context_summary(memory_hits),
            retrieval_run_refs=list(memory_search.retrieval_run_refs),
        )

    def _latest_checkpoint(self, conversation_id: str) -> ConversationSummaryCheckpoint | None:
        return self.conversation_summaries.latest_checkpoint(
            conversation_id,
            self._state.list_summary_checkpoints(),
        )

    def _build_summary_checkpoint(
        self,
        conversation: ConversationSession,
        *,
        force: bool = False,
        created_by: str = "system",
    ) -> ConversationSummaryCheckpoint | None:
        return self.conversation_summaries.build_checkpoint(
            conversation,
            self._state.list_summary_checkpoints(),
            force=force,
            created_by=created_by,
        )

    def system_prompt(self, conversation: ConversationSession) -> str:
        scope = f"{conversation.space_type}:{conversation.space_id}"
        prompt = (
            self._prompt_registry.get_active("agent_runtime_guardrails")
            if self._prompt_registry is not None
            else builtin_prompt("agent_runtime_guardrails")
        )
        return prompt.system_template.replace("{scope}", scope)

    def history_snapshot(self, conversation: ConversationSession) -> str:
        segments: list[str] = []
        latest_checkpoint = self._latest_checkpoint(conversation.id)
        if latest_checkpoint:
            segments.append(f"Conversation checkpoint:\n{latest_checkpoint.summary_text}")

        recent_messages = self._recent_text_messages(conversation)[-6:]
        if recent_messages:
            turns = []
            for message in recent_messages:
                text = self._message_text(message)
                if not text:
                    continue
                actor = "User" if message.role == "user" else "Agent"
                turns.append(f"{actor}: {text}")
            if turns:
                segments.append("Recent turns:\n" + "\n".join(turns))

        bindings = list(self._state.session_candidate_refs(conversation.id))
        if bindings:
            segments.append("Session-only candidate knowledge:\n" + "\n".join(f"- {ref}" for ref in bindings))

        return "\n\n".join(segments) if segments else "No prior conversation memory."

    def context_snapshot(
        self,
        conversation: ConversationSession,
        *,
        tools: list[ToolDefinition] | None = None,
        memory_hits: list[SystemImageMemoryHit] | None = None,
    ) -> str:
        sections: list[str] = [
            "[space]",
            f"space_type={conversation.space_type}",
            f"space_id={conversation.space_id}",
        ]
        sections.extend(self._project_context(conversation))
        sections.extend(self._version_context(conversation))
        sections.extend(self._us_context(conversation))
        sections.extend(self._operational_context(conversation))
        sections.extend(self._system_image_context(conversation))
        sections.extend(self._project_long_term_memory_context(conversation))
        sections.extend(self._retrieved_system_image_context(memory_hits or []))
        if tools is not None:
            sections.append("[tool_catalog]")
            sections.append(compact_tool_catalog_json(tools, conversation))
        return "\n".join(sections)

    def _project_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.project_id:
            return []
        project = self._state.project_snapshot(conversation.project_id)
        if project is None:
            return []
        return [
            "[project]",
            (
                f"project_id={project.id}; name={project.name}; progress={project.progress}; risk={project.risk}; "
                f"blocked_items={project.blocked_items}; pending_approvals={project.pending_approvals}; "
                f"system_image_status={project.system_image_status}"
            ),
        ]

    def _version_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.project_id:
            return []
        version = self._state.latest_version_snapshot(conversation.project_id)
        if version is None:
            return []
        return [
            "[version]",
            (
                f"version_id={version.id}; name={version.name}; status={version.status}; "
                f"us_closed={version.us_closed}; us_total={version.us_total}; pending_runs={version.pending_runs}; "
                f"pending_approvals={version.pending_approvals}"
            ),
        ]

    def _us_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.us_id:
            return []
        us_item = self._state.us_snapshot(conversation.us_id)
        if us_item is None:
            return []
        sections = [
            "[us_work_item]",
            (
                f"us_id={us_item.id}; title={us_item.title}; owner={us_item.owner}; status={us_item.status}; "
                f"risk={us_item.risk}; progress={us_item.progress}; next_action={us_item.next_action}"
            ),
        ]
        for lane in us_item.asset_lanes:
            sections.append(f"asset_lane={lane.label}; status={lane.status}; summary={lane.summary}")
        return sections

    def _operational_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.project_id:
            return []
        sections: list[str] = ["[operations]"]
        for run in self._state.recent_run_snapshots(conversation.project_id):
            sections.append(f"run={run.id}; title={run.title}; status={run.status}; channel={run.channel}; summary={run.summary}")
        for approval in self._state.recent_approval_snapshots(conversation.project_id):
            sections.append(f"approval={approval.id}; title={approval.title}; status={approval.status}; summary={approval.summary}")
        return sections if len(sections) > 1 else []

    def _system_image_context(self, conversation: ConversationSession) -> list[str]:
        return self.system_image_memory_context.context_sections(conversation.project_id)

    def _project_long_term_memory_context(self, conversation: ConversationSession) -> list[str]:
        project_id = conversation.project_id
        if not project_id:
            return []
        owner_ref = f"project:{project_id}"
        memory_items = [
            item
            for item in self._state.list_memory_items()
            if item.owner_ref == owner_ref and item.memory_scope == "project_long_term" and item.status == "active"
        ]
        if not memory_items:
            return []
        sections = ["[project_long_term_memory]"]
        for item in sorted(memory_items, key=lambda memory: memory.created_at)[-6:]:
            summary = re.sub(r"\s+", " ", item.summary).strip()[:420]
            sections.append(
                "agent_memory="
                f"{item.id}; summary={summary}; "
                f"sources={', '.join(item.source_refs[:6]) or 'none'}; "
                f"objects={', '.join(item.object_refs[:6]) or 'none'}; "
                f"evidence={', '.join(item.evidence_refs[:6]) or 'none'}"
            )
        return sections

    def _conversation_for_memory_query(
        self,
        *,
        conversation_id: str | None,
        agent_goal_id: str | None,
        space_ref: str | None,
    ) -> ConversationSession:
        if agent_goal_id:
            goal = self._state.get_goal(agent_goal_id)
            return self._state.get_conversation(goal.conversation_id)
        if conversation_id:
            return self._state.get_conversation(conversation_id)
        if space_ref:
            space_type, _, space_id = space_ref.partition(":")
            if not space_type or not space_id:
                raise KeyError(space_ref)
            for conversation in self._state.list_conversations():
                if conversation.space_type == space_type and conversation.space_id == space_id:
                    return conversation
                if space_type == "project" and conversation.project_id == space_id:
                    return conversation
        raise KeyError("conversation_id, agent_goal_id, or space_ref is required")

    @staticmethod
    def _working_memory_view(goal: AgentGoal | None) -> dict[str, Any]:
        if goal is None:
            return {
                "active_goal_id": None,
                "status": "idle",
                "current_step_id": None,
                "pause_reason": None,
            }
        current_step = next((step for step in goal.steps if step.status == "running"), None)
        if current_step is None:
            current_step = next((step for step in goal.steps if step.status == "blocked"), None)
        return {
            "active_goal_id": goal.id,
            "status": goal.status,
            "current_step_id": current_step.id if current_step else None,
            "pause_reason": goal.pause_reason,
            "steps_completed": goal.steps_completed,
            "max_steps": goal.max_steps,
        }

    def _project_long_term_memory_view(self, project_id: str | None) -> dict[str, Any]:
        view = self.system_image_memory_context.long_term_project_refs(project_id)
        memory_items = self._project_memory_items(project_id) if project_id else []
        return {
            **view,
            "memory_item_refs": [f"agent_memory:{item.id}:{item.status}" for item in memory_items],
            "memory_items": [
                {
                    "id": item.id,
                    "memory_scope": item.memory_scope,
                    "summary": item.summary,
                    "source_refs": item.source_refs[:8],
                    "object_refs": item.object_refs[:8],
                    "evidence_refs": item.evidence_refs[:8],
                    "created_at": item.created_at,
                }
                for item in memory_items[-6:]
            ],
        }

    def _project_memory_items(self, project_id: str) -> list[AgentMemoryItem]:
        owner_ref = f"project:{project_id}"
        items = [
            item
            for item in self._state.list_memory_items()
            if item.owner_ref == owner_ref and item.memory_scope == "project_long_term" and item.status == "active"
        ]
        return sorted(items, key=lambda item: item.created_at)

    def _candidate_memory_view(self, conversation: ConversationSession, project_id: str | None) -> dict[str, Any]:
        session_refs = list(self._state.session_candidate_refs(conversation.id))
        overlay_refs = (
            list(self._state.candidate_overlay_refs(project_id))
            if project_id
            else []
        )
        return {
            "session_only_refs": session_refs,
            "candidate_overlay_refs": overlay_refs,
        }

    async def retrieve_system_image_memory(
        self,
        conversation: ConversationSession,
        query: str | None = None,
        *,
        limit: int = 8,
        trace: bool = False,
    ):
        return await self.system_image_retriever.search_project_memory(
            conversation,
            query or self._retrieval_query(conversation),
            limit=limit,
            trace=trace,
        )

    def _retrieved_system_image_context(self, memory_hits: list[SystemImageMemoryHit]) -> list[str]:
        if not memory_hits:
            return []
        sections = ["[retrieved_system_image_memory]"]
        for hit in memory_hits:
            sections.append(
                f"memory_ref={hit.ref}; kind={hit.kind}; score={hit.score}; summary={hit.summary}"
            )
        return sections

    @staticmethod
    def _retrieved_context_summary(memory_hits: list[SystemImageMemoryHit]) -> str:
        if not memory_hits:
            return "no retrieved system image memory"
        kinds = ", ".join(sorted({hit.kind for hit in memory_hits}))
        top_refs = ", ".join(hit.ref for hit in memory_hits[:3])
        return f"{len(memory_hits)} hits across {kinds}; top_refs={top_refs}"

    @staticmethod
    def _message_text(message: ConversationMessage) -> str:
        text = " ".join(block.text.strip() for block in message.blocks if block.text.strip())
        return re.sub(r"\s+", " ", text)

    def _retrieval_query(self, conversation: ConversationSession) -> str:
        recent_messages = self._recent_text_messages(conversation)[-4:]
        query_parts = [self._message_text(message) for message in recent_messages]
        if conversation.us_id:
            query_parts.append(conversation.us_id)
        if conversation.project_id:
            project = self._state.project_snapshot(conversation.project_id)
            if project is not None:
                query_parts.append(project.name)
        return " ".join(part for part in query_parts if part).strip()

    @staticmethod
    def _recent_text_messages(conversation: ConversationSession) -> list[ConversationMessage]:
        return [
            message
            for message in conversation.messages
            if message.content_type in {"text", "markdown"} and message.status == "completed"
        ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AgentMemoryContext",
    "AgentMemoryManager",
    "memory_context_hash",
    "memory_context_summary",
]
