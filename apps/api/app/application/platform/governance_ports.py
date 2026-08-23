from __future__ import annotations

from typing import Protocol

from ..agent.agent_models import ConversationSession
from ..quality_loop.governance_models import MergedResolution
from ..quality_loop.quality_models import (
    ApprovalDetail,
    ExecutionEvidence,
    ReleaseDecision,
    ReleaseReadiness,
    USItem,
)
from ..system_image.system_image_models import BaselineRecord
from .project_models import ProjectCard, VersionSummary
from .tool_models import ToolInvocation


class GovernanceWorkspacePort(Protocol):
    """Facts and persistence operations required by governance use cases."""

    def resolve_project_id(self, invocation: ToolInvocation) -> str | None: ...

    def require_project_access(self, project_id: str) -> None: ...

    def has_project(self, project_id: str) -> bool: ...

    def get_project(self, project_id: str) -> ProjectCard: ...

    def save_project(self, project: ProjectCard) -> None: ...

    def list_versions(self, project_id: str) -> list[VersionSummary]: ...

    def replace_versions(self, project_id: str, versions: list[VersionSummary]) -> None: ...

    def list_us_items(self, project_id: str) -> list[USItem]: ...

    def project_id_for_task(self, task_id: str) -> str | None: ...

    def get_approval(self, project_id: str, approval_id: str) -> ApprovalDetail | None: ...

    def list_approvals(self, project_id: str) -> list[ApprovalDetail]: ...

    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None: ...

    def save_approval(self, project_id: str, approval: ApprovalDetail) -> int:
        """Persist one approval and return the committed pending count."""
        ...

    def get_release_readiness(self, version_id: str) -> ReleaseReadiness | None: ...

    def save_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None: ...

    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None: ...

    def save_release_decision(self, decision: ReleaseDecision) -> None: ...

    def list_execution_evidence(self, project_id: str) -> list[ExecutionEvidence]: ...

    def list_baselines(self, project_id: str) -> list[BaselineRecord]: ...

    def replace_baselines(self, project_id: str, baselines: list[BaselineRecord]) -> None: ...

    def persist_system_image(self, project_id: str) -> None: ...

    def get_merged_resolution(self, resolution_id: str) -> MergedResolution | None: ...

    def list_merged_resolutions(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> list[MergedResolution]: ...

    def save_merged_resolution(self, resolution: MergedResolution) -> None: ...


__all__ = ["GovernanceWorkspacePort"]
