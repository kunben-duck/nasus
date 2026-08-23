from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from ...application.platform.project_models import ProjectCard
from ...application.platform.read_model_refresh import ProjectReadModelRefreshApplicationService
from ...application.system_image.persistence import (
    SystemImagePersistenceApplicationService,
)
from ...application.system_image.ports import SystemImageWorkspacePort
from ...application.system_image.system_image_models import RawAssetRecord


class CompatibilitySystemImageIngestionProjection:
    """Adapter for the mutable V1 projection while repositories are extracted.

    The application use case sees one explicit port. Locking, compatibility
    dictionaries, repository persistence, and read-model refresh remain
    infrastructure concerns and can be replaced without changing ingestion
    policy.
    """

    def __init__(
        self,
        mutation_guard: Callable[[str], AbstractContextManager[None]],
        workspace: SystemImageWorkspacePort,
        read_model_refresh: ProjectReadModelRefreshApplicationService,
    ) -> None:
        self._mutation_guard = mutation_guard
        self._workspace = workspace
        self._persistence = SystemImagePersistenceApplicationService(workspace)
        self._read_model_refresh = read_model_refresh

    def mutation_guard(self, project_id: str) -> AbstractContextManager[None]:
        return self._mutation_guard(project_id)

    def get_project(self, project_id: str) -> ProjectCard:
        return self._workspace.get_project(project_id)

    def list_sources(self, project_id: str) -> list[RawAssetRecord]:
        return self._workspace.list_raw_assets(project_id)

    def replace_sources(self, project_id: str, sources: list[RawAssetRecord]) -> None:
        self._workspace.replace_raw_assets(project_id, sources)

    def save_project(self, project: ProjectCard) -> None:
        self._workspace.save_project(project)

    def clear_derived_context(self, project_id: str) -> None:
        self._workspace.replace_raw_asset_chunks(project_id, [])
        self._workspace.replace_embedding_records(project_id, [])
        self._workspace.replace_retrieval_runs(project_id, [])
        self._workspace.replace_rerank_records(project_id, [])
        self._workspace.replace_task_contexts(project_id, [])
        self._workspace.replace_quality_profiles(project_id, [])

    def clear_chunks(self, project_id: str) -> None:
        self._workspace.replace_raw_asset_chunks(project_id, [])

    def persist(self, project_id: str) -> None:
        self._persistence.persist(project_id)

    def refresh(self, project_id: str) -> None:
        self._read_model_refresh.refresh_system_image(project_id)


__all__ = ["CompatibilitySystemImageIngestionProjection"]
