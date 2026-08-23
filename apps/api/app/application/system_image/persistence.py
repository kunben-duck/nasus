from __future__ import annotations

from .ports import SystemImageWorkspacePort


class SystemImagePersistenceApplicationService:
    """Persists the current system-image read model snapshot for a project."""

    def __init__(self, workspace: SystemImageWorkspacePort) -> None:
        self._workspace = workspace

    def persist(self, project_id: str) -> None:
        self._workspace.persist_system_image(project_id)


__all__ = ["SystemImagePersistenceApplicationService"]
