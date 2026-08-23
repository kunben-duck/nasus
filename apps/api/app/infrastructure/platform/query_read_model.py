from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...application.agent.agent_models import AgentMemoryItem, ConversationSession
from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.platform.read_query_ports import (
    AgentQueryReadPort,
    TopLevelContentReadPort,
)
from ...application.quality_loop.quality_models import (
    ApprovalSummary,
    AssetLane,
    RunSummary,
    USItem,
)
from ..persistence.conversation_repository import ConversationRepository
from ..persistence.project_repository import ProjectRepository
from ..persistence.quality_loop_repository import QualityLoopRepository


@dataclass(frozen=True)
class PlatformQueryProjectionFacts:
    projects: Mapping[str, ProjectCard]
    versions: Mapping[str, list[VersionSummary]]
    us_items: Mapping[str, list[USItem]]
    asset_lanes: Mapping[str, list[AssetLane]]
    runs: Mapping[str, list[RunSummary]]
    approvals: Mapping[str, list[ApprovalSummary]]
    conversations: Mapping[str, ConversationSession]
    agent_memory_items: Mapping[str, AgentMemoryItem]


@dataclass(frozen=True)
class PlatformQueryProjectionAdapters:
    visible_project_ids: Callable[[], set[str]]
    current_user_id: Callable[[], str]
    get_system_image: Callable[[str], Any]
    list_documentation: Callable[[], Sequence[Any]]


class CompatibilityPlatformQueryReadModel(
    AgentQueryReadPort,
    TopLevelContentReadPort,
):
    """Anti-corruption adapter over transitional in-process read projections."""

    def __init__(
        self,
        facts: PlatformQueryProjectionFacts,
        adapters: PlatformQueryProjectionAdapters,
    ) -> None:
        self._facts = facts
        self._adapters = adapters

    def visible_project_ids(self) -> set[str]:
        return set(self._adapters.visible_project_ids())

    def current_user_id(self) -> str:
        return self._adapters.current_user_id()

    def list_projects(self) -> tuple[ProjectCard, ...]:
        return tuple(self._facts.projects.values())

    def get_project(self, project_id: str) -> ProjectCard:
        return self._facts.projects[project_id]

    def list_versions(self, project_id: str) -> tuple[VersionSummary, ...]:
        return tuple(self._facts.versions.get(project_id, ()))

    def list_us_items(self, project_id: str) -> tuple[USItem, ...]:
        return tuple(self._facts.us_items.get(project_id, ()))

    def list_asset_lanes(self, us_id: str) -> tuple[AssetLane, ...]:
        return tuple(self._facts.asset_lanes.get(us_id, ()))

    def list_runs(self, project_id: str) -> tuple[RunSummary, ...]:
        return tuple(self._facts.runs.get(project_id, ()))

    def list_approvals(self, project_id: str) -> tuple[ApprovalSummary, ...]:
        return tuple(self._facts.approvals.get(project_id, ()))

    def list_agent_memory_items(self) -> tuple[AgentMemoryItem, ...]:
        return tuple(self._facts.agent_memory_items.values())

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self._facts.conversations.values())

    def get_conversation(self, conversation_id: str) -> ConversationSession | None:
        return self._facts.conversations.get(conversation_id)

    def get_system_image(self, project_id: str) -> Any:
        return self._adapters.get_system_image(project_id)

    def list_documentation(self) -> tuple[Any, ...]:
        return tuple(self._adapters.list_documentation())


class SQLAlchemyAgentQueryReadModel(AgentQueryReadPort):
    """Durable, authorization-filtered read model for Agent query tools."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        quality_loop: QualityLoopRepository,
        conversations: ConversationRepository,
        visible_project_ids: Callable[[], set[str]],
        current_user_id: Callable[[], str],
        project_id_for_us: Callable[[str], str | None],
        get_system_image: Callable[[str], Any],
    ) -> None:
        self._projects = projects
        self._quality_loop = quality_loop
        self._conversations = conversations
        self._visible_project_ids = visible_project_ids
        self._current_user_id = current_user_id
        self._project_id_for_us = project_id_for_us
        self._get_system_image = get_system_image

    def list_projects(self) -> tuple[ProjectCard, ...]:
        visible_ids = self._visible_ids()
        return tuple(
            project
            for project in self._projects.list_projects()
            if project.id in visible_ids
        )

    def get_project(self, project_id: str) -> ProjectCard:
        self._require_visible(project_id)
        project = self._projects.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def list_versions(self, project_id: str) -> tuple[VersionSummary, ...]:
        if project_id not in self._visible_ids():
            return ()
        return tuple(self._projects.list_versions(project_id))

    def list_us_items(self, project_id: str) -> tuple[USItem, ...]:
        if project_id not in self._visible_ids():
            return ()
        return tuple(self._quality_loop.list_us_items(project_id))

    def list_asset_lanes(self, us_id: str) -> tuple[AssetLane, ...]:
        project_id = self._project_id_for_us(us_id)
        if not project_id or project_id not in self._visible_ids():
            return ()
        return tuple(self._quality_loop.list_asset_lanes(project_id).get(us_id, ()))

    def list_runs(self, project_id: str) -> tuple[RunSummary, ...]:
        if project_id not in self._visible_ids():
            return ()
        return tuple(self._quality_loop.list_runs(project_id))

    def list_approvals(self, project_id: str) -> tuple[ApprovalSummary, ...]:
        if project_id not in self._visible_ids():
            return ()
        return tuple(self._quality_loop.list_approvals(project_id))

    def list_agent_memory_items(self) -> tuple[AgentMemoryItem, ...]:
        visible_owner_refs = {
            f"project:{project_id}" for project_id in self._visible_ids()
        }
        return tuple(
            item
            for item in self._conversations.load_agent_memory_items()
            if item.owner_ref in visible_owner_refs
        )

    def get_conversation(self, conversation_id: str) -> ConversationSession | None:
        conversation = self._conversations.get_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.project_id:
            return (
                conversation
                if conversation.project_id in self._visible_ids()
                else None
            )
        return (
            conversation
            if conversation.initiator_id == self._current_user_id()
            else None
        )

    def get_system_image(self, project_id: str) -> Any:
        self._require_visible(project_id)
        return self._get_system_image(project_id)

    def _visible_ids(self) -> set[str]:
        return set(self._visible_project_ids())

    def _require_visible(self, project_id: str) -> None:
        if project_id not in self._visible_ids():
            raise KeyError(project_id)


__all__ = [
    "CompatibilityPlatformQueryReadModel",
    "PlatformQueryProjectionAdapters",
    "PlatformQueryProjectionFacts",
    "SQLAlchemyAgentQueryReadModel",
]
