from __future__ import annotations

from ...application.platform.project_models import ProjectCard
from ...application.platform.project_workspace_ports import ProjectWorkspaceSnapshot
from ..persistence.project_repository import ProjectRepository
from ..persistence.quality_loop_repository import QualityLoopRepository
from ..persistence.system_image_repository import SystemImageRepository


class SQLAlchemyProjectWorkspaceReadModel:
    """PostgreSQL-backed project workspace query adapter.

    This adapter deliberately composes read models across bounded contexts. It
    does not mutate domain state and does not hydrate the compatibility store.
    """

    def __init__(
        self,
        project_repository: ProjectRepository,
        quality_loop_repository: QualityLoopRepository,
        system_image_repository: SystemImageRepository,
    ) -> None:
        self._projects = project_repository
        self._quality_loop = quality_loop_repository
        self._system_image = system_image_repository

    def list_projects(self) -> list[ProjectCard]:
        return self._projects.list_projects()

    def get_project(self, project_id: str) -> ProjectCard | None:
        return self._projects.get_project(project_id)

    def load_workspace(self, project_id: str) -> ProjectWorkspaceSnapshot | None:
        project = self.get_project(project_id)
        if project is None:
            return None

        versions = self._projects.list_versions(project_id)
        active_version_id = versions[0].id if versions else None
        return ProjectWorkspaceSnapshot(
            project=project,
            versions=versions,
            us_items=self._quality_loop.list_us_items(
                project_id,
                active_version_id,
            ),
            asset_lanes=self._quality_loop.list_asset_lanes(project_id),
            runs=self._quality_loop.list_runs(project_id),
            approvals=self._quality_loop.list_approvals(project_id),
            task_contexts=self._system_image.list_task_contexts(project_id),
            quality_profiles=self._system_image.list_quality_profiles(project_id),
            quality_asset_packs=self._quality_loop.list_quality_asset_packs(project_id),
            execution_evidence=self._quality_loop.list_execution_evidence(project_id),
            failure_reports=self._quality_loop.list_failure_reports(project_id),
            release_decisions=self._quality_loop.list_release_decisions(project_id),
            release_readiness={
                version.id: readiness
                for version in versions
                if (readiness := self._quality_loop.get_release_readiness(version.id)) is not None
            },
        )

    def get_run_detail(self, project_id: str, run_id: str):
        return self._quality_loop.get_run_detail(project_id, run_id)

    def get_approval_detail(self, project_id: str, approval_id: str):
        return self._quality_loop.get_approval_detail(project_id, approval_id)


__all__ = ["SQLAlchemyProjectWorkspaceReadModel"]
