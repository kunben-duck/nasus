from __future__ import annotations

from .read_model_ports import ProjectReadModelProjectionPort


class ProjectReadModelRefreshApplicationService:
    """Refreshes project read-model caches from persistence."""

    def __init__(self, projection: ProjectReadModelProjectionPort) -> None:
        self._projection = projection

    def refresh_project(self, project_id: str) -> None:
        self._projection.refresh_project(project_id)

    def refresh_system_image(self, project_id: str) -> None:
        self._projection.refresh_system_image(project_id)


__all__ = ["ProjectReadModelRefreshApplicationService"]
