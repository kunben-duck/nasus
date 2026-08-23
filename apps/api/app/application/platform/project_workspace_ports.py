from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..agent.agent_models import ConversationSession
from ..quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    ReleaseDecision,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ..system_image.system_image_models import QualityProfile, TaskContext
from .project_models import ProjectCard, VersionSummary
from .tool_models import ToolInvocation, ToolInvocationRequest


@dataclass(frozen=True)
class ProjectWorkspaceSnapshot:
    """Durable cross-domain read model for one project workspace."""

    project: ProjectCard
    versions: list[VersionSummary] = field(default_factory=list)
    us_items: list[USItem] = field(default_factory=list)
    asset_lanes: dict[str, list[AssetLane]] = field(default_factory=dict)
    runs: list[RunSummary] = field(default_factory=list)
    approvals: list[ApprovalSummary] = field(default_factory=list)
    task_contexts: list[TaskContext] = field(default_factory=list)
    quality_profiles: list[QualityProfile] = field(default_factory=list)
    quality_asset_packs: list[QualityAssetPack] = field(default_factory=list)
    execution_evidence: list[ExecutionEvidence] = field(default_factory=list)
    failure_reports: list[FailureReport] = field(default_factory=list)
    release_decisions: list[ReleaseDecision] = field(default_factory=list)
    release_readiness: dict[str, ReleaseReadiness] = field(default_factory=dict)


class ProjectWorkspaceReadPort(Protocol):
    def list_projects(self) -> list[ProjectCard]: ...

    def get_project(self, project_id: str) -> ProjectCard | None: ...

    def load_workspace(self, project_id: str) -> ProjectWorkspaceSnapshot | None: ...

    def get_run_detail(self, project_id: str, run_id: str) -> RunDetail | None: ...

    def get_approval_detail(self, project_id: str, approval_id: str) -> ApprovalDetail | None: ...


class ProjectWorkspaceAuthorizationPort(Protocol):
    def visible_project_ids(self) -> set[str]: ...

    def require_project_access(self, project_id: str) -> object | None: ...


class ProjectWorkspaceToolPort(Protocol):
    async def create_tool_invocation(self, payload: ToolInvocationRequest) -> ToolInvocation: ...


class ProjectWorkspaceConversationPort(Protocol):
    def get_or_create_conversation(
        self,
        space_type: str,
        space_id: str,
        title: str,
        *,
        project_id: str | None = None,
        version_id: str | None = None,
        us_id: str | None = None,
    ) -> ConversationSession: ...


__all__ = [
    "ProjectWorkspaceAuthorizationPort",
    "ProjectWorkspaceConversationPort",
    "ProjectWorkspaceReadPort",
    "ProjectWorkspaceSnapshot",
    "ProjectWorkspaceToolPort",
]
