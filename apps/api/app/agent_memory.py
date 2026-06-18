from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import ConversationMessage, ConversationSession, ToolDefinition

if TYPE_CHECKING:
    from .store import ApplicationStore


@dataclass(frozen=True)
class AgentMemoryContext:
    system_prompt: str
    context_snapshot: str
    history_snapshot: str
    recent_turn_count: int
    checkpoint_count: int


class AgentMemoryManager:
    """Builds the structured context package used before LLM-backed agent calls."""

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    def build_context(
        self,
        conversation: ConversationSession,
        *,
        tools: list[ToolDefinition] | None = None,
    ) -> AgentMemoryContext:
        history_snapshot = self.history_snapshot(conversation)
        recent_turn_count = len(self._recent_text_messages(conversation)[-6:])
        checkpoint_count = sum(
            1
            for checkpoint in self.store.conversation_summary_checkpoints.values()
            if checkpoint.conversation_id == conversation.id
        )
        return AgentMemoryContext(
            system_prompt=self.system_prompt(conversation),
            context_snapshot=self.context_snapshot(conversation, tools=tools),
            history_snapshot=history_snapshot,
            recent_turn_count=recent_turn_count,
            checkpoint_count=checkpoint_count,
        )

    @staticmethod
    def system_prompt(conversation: ConversationSession) -> str:
        scope = f"{conversation.space_type}:{conversation.space_id}"
        return (
            "You are Nasus Agent, the agent-first quality orchestration service. "
            "Plan and answer from the provided memory package, use registered tools for any write action, "
            "and never bypass confirmation, approval, policy, audit, or domain-object boundaries. "
            f"Current scope is {scope}."
        )

    def history_snapshot(self, conversation: ConversationSession) -> str:
        segments: list[str] = []
        latest_checkpoint = self.store._latest_checkpoint_for_conversation(conversation.id)
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

        bindings = [
            binding.candidate_object_ref
            for binding in self.store.session_knowledge_bindings.values()
            if binding.conversation_id == conversation.id
        ]
        if bindings:
            segments.append("Session-only candidate knowledge:\n" + "\n".join(f"- {ref}" for ref in bindings))

        return "\n\n".join(segments) if segments else "No prior conversation memory."

    def context_snapshot(
        self,
        conversation: ConversationSession,
        *,
        tools: list[ToolDefinition] | None = None,
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
        if tools is not None:
            sections.append("[tool_catalog]")
            sections.append(
                json.dumps(
                    [
                        {
                            "tool_id": tool.tool_id,
                            "risk_level": tool.risk_level,
                            "confirmation_mode": tool.confirmation_mode,
                            "required_context": tool.required_context,
                            "produced_objects": tool.produced_objects,
                        }
                        for tool in tools
                    ],
                    ensure_ascii=False,
                )
            )
        return "\n".join(sections)

    def _project_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.project_id or conversation.project_id not in self.store.projects:
            return []
        project = self.store.projects[conversation.project_id]
        return [
            "[project]",
            (
                f"project_id={project.id}; name={project.name}; progress={project.progress}; risk={project.risk}; "
                f"blocked_items={project.blocked_items}; pending_approvals={project.pending_approvals}; "
                f"system_image_status={project.system_image_status}"
            ),
        ]

    def _version_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.project_id or not self.store.versions.get(conversation.project_id):
            return []
        version = self.store.versions[conversation.project_id][0]
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
        us_item = next(
            (
                item
                for items in self.store.us_items.values()
                for item in items
                if item.id == conversation.us_id
            ),
            None,
        )
        if us_item is None:
            return []
        sections = [
            "[us_work_item]",
            (
                f"us_id={us_item.id}; title={us_item.title}; owner={us_item.owner}; status={us_item.status}; "
                f"risk={us_item.risk}; progress={us_item.progress}; next_action={us_item.next_action}"
            ),
        ]
        for lane in self.store.asset_lanes.get(us_item.id, []):
            sections.append(f"asset_lane={lane.label}; status={lane.status}; summary={lane.summary}")
        return sections

    def _operational_context(self, conversation: ConversationSession) -> list[str]:
        if not conversation.project_id:
            return []
        sections: list[str] = ["[operations]"]
        for run in self.store.runs.get(conversation.project_id, [])[:3]:
            sections.append(f"run={run.id}; title={run.title}; status={run.status}; channel={run.channel}; summary={run.summary}")
        for approval in self.store.approvals.get(conversation.project_id, [])[:3]:
            sections.append(f"approval={approval.id}; title={approval.title}; status={approval.status}; summary={approval.summary}")
        return sections if len(sections) > 1 else []

    def _system_image_context(self, conversation: ConversationSession) -> list[str]:
        project_id = conversation.project_id
        if not project_id:
            return []
        sections = ["[system_image]"]
        for baseline in self.store.baselines.get(project_id, [])[:2]:
            sections.append(
                f"baseline={baseline.id}; kind={baseline.kind}; status={baseline.status}; "
                f"objects={baseline.object_count}; relationships={baseline.relationship_count}; "
                f"metrics={baseline.metric_snapshot_count}"
            )
        for source in self.store.raw_assets.get(project_id, [])[:6]:
            sections.append(
                f"source={source.source_type}; status={source.ingestion_status}; uri={source.source_uri}; "
                f"hash={source.content_hash or 'pending'}"
            )
        for item in self.store.knowledge_objects.get(project_id, [])[:6]:
            sections.append(
                f"context_object={item.id}; name={item.name}; type={item.type}; branch={item.branch}; "
                f"confidence={item.confidence}; freshness={item.freshness}"
            )
        for relationship in self.store.context_relationships.get(project_id, [])[:6]:
            sections.append(
                f"relationship={relationship.relationship_type}; from={relationship.from_object_id}; "
                f"to={relationship.to_object_id}; confidence={relationship.confidence}"
            )
        for metric in self.store.quality_metric_snapshots.get(project_id, [])[:4]:
            sections.append(f"metric={metric.metric_group}; values={json.dumps(metric.metrics, ensure_ascii=False)}")
        return sections if len(sections) > 1 else []

    @staticmethod
    def _message_text(message: ConversationMessage) -> str:
        text = " ".join(block.text.strip() for block in message.blocks if block.text.strip())
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _recent_text_messages(conversation: ConversationSession) -> list[ConversationMessage]:
        return [
            message
            for message in conversation.messages
            if message.content_type in {"text", "markdown"} and message.status == "completed"
        ]


def memory_context_hash(memory_context: AgentMemoryContext) -> str:
    payload = "\n\n".join(
        [
            memory_context.system_prompt,
            memory_context.context_snapshot,
            memory_context.history_snapshot,
        ]
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def memory_context_summary(memory_context: AgentMemoryContext) -> str:
    sections = [
        line.strip("[]")
        for line in memory_context.context_snapshot.splitlines()
        if line.startswith("[") and line.endswith("]")
    ]
    section_summary = ", ".join(sections[:8]) if sections else "space"
    return (
        f"sections={section_summary}; "
        f"recent_turns={memory_context.recent_turn_count}; "
        f"checkpoints={memory_context.checkpoint_count}"
    )
