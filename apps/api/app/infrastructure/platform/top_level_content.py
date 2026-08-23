from __future__ import annotations

from collections.abc import Callable, Sequence

from ...application.agent.agent_models import ConversationSession
from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.platform.read_models import DocumentationEntry
from ...application.platform.read_query_ports import TopLevelContentReadPort
from ...application.quality_loop.quality_models import RunSummary
from ..persistence.conversation_repository import ConversationRepository
from ..persistence.project_repository import ProjectRepository
from ..persistence.quality_loop_repository import QualityLoopRepository


class SQLAlchemyTopLevelContentReadModel(TopLevelContentReadPort):
    """PostgreSQL-backed portfolio projection for top-level studio pages.

    This adapter intentionally performs fresh repository reads. Top-level pages
    are served by every API replica, so process-local compatibility projections
    cannot be their source of truth.
    """

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        quality_loop: QualityLoopRepository,
        conversations: ConversationRepository,
        visible_project_ids: Callable[[], set[str]],
        current_user_id: Callable[[], str],
        documentation: Sequence[DocumentationEntry],
    ) -> None:
        self._projects = projects
        self._quality_loop = quality_loop
        self._conversations = conversations
        self._visible_project_ids = visible_project_ids
        self._current_user_id = current_user_id
        self._documentation = tuple(documentation)

    def visible_project_ids(self) -> set[str]:
        return set(self._visible_project_ids())

    def current_user_id(self) -> str:
        return self._current_user_id()

    def list_projects(self) -> tuple[ProjectCard, ...]:
        return tuple(self._projects.list_projects())

    def list_versions(self, project_id: str) -> tuple[VersionSummary, ...]:
        return tuple(self._projects.list_versions(project_id))

    def list_runs(self, project_id: str) -> tuple[RunSummary, ...]:
        return tuple(self._quality_loop.list_runs(project_id))

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self._conversations.load_all())

    def list_documentation(self) -> tuple[DocumentationEntry, ...]:
        return self._documentation


__all__ = ["SQLAlchemyTopLevelContentReadModel"]
