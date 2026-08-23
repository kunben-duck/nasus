from __future__ import annotations

from typing import Protocol


class ProjectReadModelProjectionPort(Protocol):
    """Refresh a project-scoped compatibility projection from durable state."""

    def refresh_project(self, project_id: str) -> None: ...

    def refresh_system_image(self, project_id: str) -> None: ...


__all__ = ["ProjectReadModelProjectionPort"]
