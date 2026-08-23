from __future__ import annotations

from typing import Any, Protocol, Sequence

from ..agent.agent_models import AgentMemoryItem, ConversationSession
from ..quality_loop.quality_models import ApprovalSummary, AssetLane, RunSummary, USItem
from .project_models import ProjectCard, VersionSummary


class AgentQueryReadPort(Protocol):
    """Cross-domain read projection consumed by Agent query-only use cases."""

    def list_projects(self) -> Sequence[ProjectCard]:
        ...

    def get_project(self, project_id: str) -> ProjectCard:
        ...

    def list_versions(self, project_id: str) -> Sequence[VersionSummary]:
        ...

    def list_us_items(self, project_id: str) -> Sequence[USItem]:
        ...

    def list_asset_lanes(self, us_id: str) -> Sequence[AssetLane]:
        ...

    def list_runs(self, project_id: str) -> Sequence[RunSummary]:
        ...

    def list_approvals(self, project_id: str) -> Sequence[ApprovalSummary]:
        ...

    def list_agent_memory_items(self) -> Sequence[AgentMemoryItem]:
        ...

    def get_conversation(self, conversation_id: str) -> ConversationSession | None:
        ...

    def get_system_image(self, project_id: str) -> Any:
        ...


class TopLevelContentReadPort(Protocol):
    """Portfolio projection consumed by unaffiliated top-level studio pages."""

    def visible_project_ids(self) -> set[str]:
        ...

    def current_user_id(self) -> str:
        ...

    def list_projects(self) -> Sequence[ProjectCard]:
        ...

    def list_versions(self, project_id: str) -> Sequence[VersionSummary]:
        ...

    def list_runs(self, project_id: str) -> Sequence[RunSummary]:
        ...

    def list_conversations(self) -> Sequence[ConversationSession]:
        ...

    def list_documentation(self) -> Sequence[Any]:
        ...


__all__ = ["AgentQueryReadPort", "TopLevelContentReadPort"]
