from __future__ import annotations

from .ports import ProjectVersionWorkspacePort
from .project_versions import ProjectVersionApplicationService


class QualityLoopVersionContextApplicationService:
    """Application boundary for active quality-loop version resolution."""

    def __init__(
        self,
        workspace: ProjectVersionWorkspacePort,
        project_versions: ProjectVersionApplicationService,
    ) -> None:
        self._workspace = workspace
        self._project_versions = project_versions

    def active_or_create_version(self, project_id: str):
        return self._project_versions.active_or_create_quality_version(project_id)


__all__ = ["QualityLoopVersionContextApplicationService"]
