from __future__ import annotations

from typing import Any

from .knowledge_queries import SystemImageKnowledgeQueryApplicationService
from .lifecycle import SystemImageLifecycleApplicationService
from .ports import SystemImageOperationsPort, SystemImageWorkspacePort
from .snapshots import SystemImageSnapshotQueryApplicationService
from .source_bindings import SystemImageSourceBindingApplicationService


class SystemImageApplicationService:
    """System image use cases.

    This is the first application boundary for the system-image module. It keeps
    project HTTP routes and tool handlers from treating system-image actions as
    generic store concerns while the persistence and domain services are
    extracted.
    """

    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        operations: SystemImageOperationsPort,
    ) -> None:
        self._workspace = workspace
        self.knowledge_queries = SystemImageKnowledgeQueryApplicationService(workspace)
        self.lifecycle = SystemImageLifecycleApplicationService(operations)
        self.snapshots = SystemImageSnapshotQueryApplicationService(operations)
        self.source_bindings = SystemImageSourceBindingApplicationService(
            workspace,
            operations,
        )

    def has_project(self, project_id: str) -> bool:
        return self.source_bindings.has_project(project_id)

    def normalize_source_specs(self, payload: Any) -> Any:
        return self.source_bindings.normalize_source_specs(payload)

    def source_binding_incomplete(self, project_id: str) -> bool:
        self._require_project_access(project_id)
        return self.source_bindings.source_binding_incomplete(project_id)

    def missing_source_types(self, project_id: str) -> list[str]:
        self._require_project_access(project_id)
        return self.source_bindings.missing_source_types(project_id)

    def register_sources(
        self,
        project_id: str,
        *,
        source_specs: Any,
        registered_by_actor: str,
        registered_from_invocation_id: str | None,
    ) -> Any:
        self._require_project_access(project_id)
        return self.source_bindings.register_sources(
            project_id,
            source_specs=source_specs,
            registered_by_actor=registered_by_actor,
            registered_from_invocation_id=registered_from_invocation_id,
        )

    def ingest_sources(self, project_id: str) -> Any:
        self._require_project_access(project_id)
        return self.source_bindings.ingest_sources(project_id)

    async def materialize_context(self, project_id: str) -> Any:
        self._require_project_access(project_id)
        return await self.lifecycle.materialize_context(project_id)

    async def initialize_baseline(self, project_id: str) -> Any:
        self._require_project_access(project_id)
        return await self.lifecycle.initialize_baseline(project_id)

    def list_knowledge_objects(self, project_id: str) -> Any:
        self._require_project_access(project_id)
        return self.knowledge_queries.list_knowledge_objects(project_id)

    def get_knowledge_object(self, project_id: str, object_id: str) -> Any:
        self._require_project_access(project_id)
        return self.knowledge_queries.get_knowledge_object(project_id, object_id)

    def get_system_image(self, project_id: str) -> Any:
        self._require_project_access(project_id)
        return self.snapshots.get_system_image(project_id)

    def _require_project_access(self, project_id: str) -> None:
        self._workspace.require_project_access(project_id)
