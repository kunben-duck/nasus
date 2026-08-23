from __future__ import annotations

from typing import Protocol


class ProjectScopeReadPort(Protocol):
    """Read only the identifiers required to resolve a conversation scope."""

    def project_id_for_version(self, version_id: str) -> str | None: ...

    def project_id_for_us(self, us_id: str) -> str | None: ...

    def first_version_id(self, project_id: str) -> str | None: ...


class ProjectScopeResolutionApplicationService:
    """Resolve project/version/US identifiers for cross-space application flows."""

    def __init__(self, state: ProjectScopeReadPort) -> None:
        self._state = state

    def resolve_conversation_scope(
        self,
        space_type: str,
        space_id: str,
        *,
        project_id: str | None = None,
        version_id: str | None = None,
        us_id: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        resolved_project_id = project_id
        resolved_version_id = version_id
        resolved_us_id = us_id

        if space_type == "project":
            resolved_project_id = resolved_project_id or space_id
        elif space_type == "version":
            if resolved_project_id is None:
                resolved_project_id = self._state.project_id_for_version(space_id)
            resolved_version_id = resolved_version_id or space_id
        elif space_type == "workspace":
            resolved_us_id = resolved_us_id or space_id
            if resolved_project_id is None:
                resolved_project_id = self._state.project_id_for_us(resolved_us_id)
            if resolved_version_id is None and resolved_project_id:
                resolved_version_id = self._state.first_version_id(
                    resolved_project_id
                )

        return resolved_project_id, resolved_version_id, resolved_us_id


__all__ = [
    "ProjectScopeReadPort",
    "ProjectScopeResolutionApplicationService",
]
