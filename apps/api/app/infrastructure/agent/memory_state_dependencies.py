from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from dataclasses import dataclass
from typing import Any

from ...application.agent.agent_models import (
    AgentGoal,
    AgentMemoryItem,
    AgentMemoryLink,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from ...application.agent.ports import (
    AgentMemoryApprovalSnapshot,
    AgentMemoryAssetLaneSnapshot,
    AgentMemoryProjectSnapshot,
    AgentMemoryRunSnapshot,
    AgentMemoryUSSnapshot,
    AgentMemoryVersionSnapshot,
)
from ...application.platform.tool_models import ToolDefinition


@dataclass(frozen=True)
class AgentMemoryProjectionState:
    conversations: MutableMapping[str, ConversationSession]
    summary_checkpoints: MutableMapping[str, ConversationSummaryCheckpoint]
    memory_items: MutableMapping[str, AgentMemoryItem]
    memory_links: MutableMapping[str, AgentMemoryLink]


@dataclass(frozen=True)
class AgentMemoryPersistenceAdapters:
    upsert_summary_checkpoint: Callable[[ConversationSummaryCheckpoint], None]
    upsert_conversation: Callable[[ConversationSession], None]
    upsert_memory_item: Callable[[AgentMemoryItem], None]
    upsert_memory_link: Callable[[AgentMemoryLink], None]


@dataclass(frozen=True)
class AgentMemoryRuntimeAdapters:
    get_goal: Callable[[str], AgentGoal]
    active_goal_for_conversation: Callable[[str], AgentGoal | None]
    available_tools: Callable[[], Iterable[ToolDefinition]]


@dataclass(frozen=True)
class AgentMemoryEventAdapters:
    push_event: Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class AgentMemoryCandidateProjectionState:
    session_knowledge_bindings: MutableMapping[str, Any]
    context_object_overlays: MutableMapping[str, list[Any]]


class CompatibilityAgentMemoryCandidateQueries:
    def __init__(self, state: AgentMemoryCandidateProjectionState) -> None:
        self._state = state

    def session_candidate_refs(self, conversation_id: str) -> tuple[str, ...]:
        return tuple(
            binding.candidate_object_ref
            for binding in self._state.session_knowledge_bindings.values()
            if binding.conversation_id == conversation_id
        )

    def candidate_overlay_refs(self, project_id: str) -> tuple[str, ...]:
        return tuple(
            f"context_overlay:{overlay.id}:{overlay.status}"
            for overlay in self._state.context_object_overlays.get(project_id, [])
            if overlay.status == "candidate"
        )


@dataclass(frozen=True)
class AgentMemoryWorkspaceProjectionState:
    projects: MutableMapping[str, Any]
    versions: MutableMapping[str, list[Any]]
    us_items: MutableMapping[str, list[Any]]
    asset_lanes: MutableMapping[str, list[Any]]
    runs: MutableMapping[str, list[Any]]
    approvals: MutableMapping[str, list[Any]]


class CompatibilityAgentMemoryWorkspaceQueries:
    def __init__(self, state: AgentMemoryWorkspaceProjectionState) -> None:
        self._state = state

    def project_snapshot(
        self,
        project_id: str,
    ) -> AgentMemoryProjectSnapshot | None:
        project = self._state.projects.get(project_id)
        if project is None:
            return None
        return AgentMemoryProjectSnapshot(
            id=project.id,
            name=project.name,
            progress=project.progress,
            risk=project.risk,
            blocked_items=project.blocked_items,
            pending_approvals=project.pending_approvals,
            system_image_status=project.system_image_status,
        )

    def latest_version_snapshot(
        self,
        project_id: str,
    ) -> AgentMemoryVersionSnapshot | None:
        versions = self._state.versions.get(project_id, [])
        if not versions:
            return None
        version = versions[0]
        return AgentMemoryVersionSnapshot(
            id=version.id,
            name=version.name,
            status=version.status,
            us_closed=version.us_closed,
            us_total=version.us_total,
            pending_runs=version.pending_runs,
            pending_approvals=version.pending_approvals,
        )

    def us_snapshot(self, us_id: str) -> AgentMemoryUSSnapshot | None:
        us_item = next(
            (
                item
                for items in self._state.us_items.values()
                for item in items
                if item.id == us_id
            ),
            None,
        )
        if us_item is None:
            return None
        return AgentMemoryUSSnapshot(
            id=us_item.id,
            title=us_item.title,
            owner=us_item.owner,
            status=us_item.status,
            risk=us_item.risk,
            progress=us_item.progress,
            next_action=us_item.next_action,
            asset_lanes=tuple(
                AgentMemoryAssetLaneSnapshot(
                    label=lane.label,
                    status=lane.status,
                    summary=lane.summary,
                )
                for lane in self._state.asset_lanes.get(us_item.id, [])
            ),
        )

    def recent_run_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryRunSnapshot, ...]:
        return tuple(
            AgentMemoryRunSnapshot(
                id=run.id,
                title=run.title,
                status=run.status,
                channel=run.channel,
                summary=run.summary,
            )
            for run in self._state.runs.get(project_id, [])[:3]
        )

    def recent_approval_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryApprovalSnapshot, ...]:
        return tuple(
            AgentMemoryApprovalSnapshot(
                id=approval.id,
                title=approval.title,
                status=approval.status,
                summary=approval.summary,
            )
            for approval in self._state.approvals.get(project_id, [])[:3]
        )


__all__ = [
    "AgentMemoryCandidateProjectionState",
    "AgentMemoryEventAdapters",
    "AgentMemoryPersistenceAdapters",
    "AgentMemoryProjectionState",
    "AgentMemoryRuntimeAdapters",
    "AgentMemoryWorkspaceProjectionState",
    "CompatibilityAgentMemoryCandidateQueries",
    "CompatibilityAgentMemoryWorkspaceQueries",
]
