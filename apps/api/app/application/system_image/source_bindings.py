from __future__ import annotations

from typing import Any

from .ports import SystemImageOperationsPort, SystemImageWorkspacePort


class SystemImageSourceBindingApplicationService:
    """System-image source binding and ingestion use cases."""

    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        operations: SystemImageOperationsPort,
    ) -> None:
        self._workspace = workspace
        self._operations = operations

    def has_project(self, project_id: str) -> bool:
        return self._workspace.has_project(project_id)

    def normalize_source_specs(self, payload: Any) -> Any:
        return self._operations.source_ingestion.normalize_specs(payload)

    def source_binding_incomplete(self, project_id: str) -> bool:
        return self._operations.source_binding_incomplete(project_id)

    def missing_source_types(self, project_id: str) -> list[str]:
        return self._operations.missing_source_types(project_id)

    def register_sources(
        self,
        project_id: str,
        *,
        source_specs: Any,
        registered_by_actor: str,
        registered_from_invocation_id: str | None,
    ) -> Any:
        return self._operations.register_sources(
            project_id,
            source_specs=source_specs,
            registered_by_actor=registered_by_actor,
            registered_from_invocation_id=registered_from_invocation_id,
        )

    def ingest_sources(self, project_id: str) -> Any:
        return self._operations.ingest_sources(project_id)


__all__ = ["SystemImageSourceBindingApplicationService"]
