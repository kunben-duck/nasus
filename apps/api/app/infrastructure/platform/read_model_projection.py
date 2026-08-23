from __future__ import annotations

from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol

from ...application.platform.projection_hydration import replace_projection


class ProjectProjectionRepositoryPort(Protocol):
    def get_project(self, project_id: str) -> Any: ...

    def list_versions(self, project_id: str) -> list[Any]: ...

    def load_projects(self) -> list[Any]: ...

    def load_versions(self) -> dict[str, list[Any]]: ...


class QualityLoopProjectionRepositoryPort(Protocol):
    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[Any]: ...

    def list_asset_lanes(self, project_id: str) -> dict[str, list[Any]]: ...

    def load_asset_lanes(self) -> dict[str, list[Any]]: ...

    def load_runs(self) -> tuple[dict[str, list[Any]], dict[str, Any]]: ...

    def load_approvals(self) -> tuple[dict[str, list[Any]], dict[str, Any]]: ...

    def load_quality_asset_packs(self) -> dict[str, Any]: ...

    def load_execution_evidence(self) -> dict[str, list[Any]]: ...

    def load_failure_reports(self) -> dict[str, list[Any]]: ...

    def load_release_decisions(self) -> dict[str, Any]: ...

    def load_release_readiness(self) -> dict[str, Any]: ...

    def load_merged_resolutions(self) -> dict[str, Any]: ...


class SystemImageProjectionRepositoryPort(Protocol):
    def load_project_snapshot(self, project_id: str) -> Any: ...

    def load_knowledge_objects(self) -> dict[str, list[Any]]: ...

    def load_raw_assets(self) -> dict[str, list[Any]]: ...

    def load_raw_asset_chunks(self) -> dict[str, list[Any]]: ...

    def load_baselines(self) -> dict[str, list[Any]]: ...

    def load_context_relationships(self) -> dict[str, list[Any]]: ...

    def load_context_object_overlays(self) -> dict[str, list[Any]]: ...

    def load_quality_metric_snapshots(self) -> dict[str, list[Any]]: ...

    def load_embedding_records(self) -> dict[str, list[Any]]: ...

    def load_retrieval_runs(self) -> dict[str, list[Any]]: ...

    def load_rerank_records(self) -> dict[str, list[Any]]: ...

    def load_task_contexts(self) -> dict[str, list[Any]]: ...

    def load_quality_profiles(self) -> dict[str, list[Any]]: ...


@dataclass(frozen=True)
class ProjectReadModelProjectionState:
    """Mutable compatibility projections owned by the composition root."""

    projects: MutableMapping[str, Any]
    versions: MutableMapping[str, list[Any]]
    us_items: MutableMapping[str, list[Any]]
    asset_lanes: MutableMapping[str, list[Any]]
    runs: MutableMapping[str, list[Any]]
    run_details: MutableMapping[str, Any]
    approvals: MutableMapping[str, list[Any]]
    approval_details: MutableMapping[str, Any]
    knowledge_objects: MutableMapping[str, list[Any]]
    raw_assets: MutableMapping[str, list[Any]]
    raw_asset_chunks: MutableMapping[str, list[Any]]
    baselines: MutableMapping[str, list[Any]]
    context_relationships: MutableMapping[str, list[Any]]
    context_object_overlays: MutableMapping[str, list[Any]]
    quality_metric_snapshots: MutableMapping[str, list[Any]]
    embedding_records: MutableMapping[str, list[Any]]
    retrieval_runs: MutableMapping[str, list[Any]]
    rerank_records: MutableMapping[str, list[Any]]
    task_contexts: MutableMapping[str, list[Any]]
    quality_profiles: MutableMapping[str, list[Any]]
    quality_asset_packs: MutableMapping[str, Any]
    execution_evidence: MutableMapping[str, list[Any]]
    failure_reports: MutableMapping[str, list[Any]]
    release_decisions: MutableMapping[str, Any]
    release_readiness: MutableMapping[str, Any]
    merged_resolutions: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectReadModelProjectionAdapters:
    """Repository and concurrency dependencies for read-model hydration."""

    project_repository: ProjectProjectionRepositoryPort
    quality_loop_repository: QualityLoopProjectionRepositoryPort
    system_image_repository: SystemImageProjectionRepositoryPort
    mutation_guard: Callable[[], AbstractContextManager[None]]


class CompatibilityProjectReadModelProjection:
    """Hydrate transitional projections through explicit state and ports."""

    def __init__(
        self,
        state: ProjectReadModelProjectionState,
        adapters: ProjectReadModelProjectionAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def hydrate_all(self) -> None:
        """Load the complete durable projection without rebinding shared maps."""

        with self._adapters.mutation_guard():
            state = self._state
            project_repository = self._adapters.project_repository
            quality_loop_repository = self._adapters.quality_loop_repository
            system_image_repository = self._adapters.system_image_repository

            projects = {
                project.id: project
                for project in project_repository.load_projects()
            }
            replace_projection(state.projects, projects)
            versions = project_repository.load_versions()
            replace_projection(state.versions, versions)
            replace_projection(
                state.us_items,
                {
                    project_id: quality_loop_repository.list_us_items(
                        project_id,
                        project_versions[0].id if project_versions else None,
                    )
                    for project_id in projects
                    for project_versions in [versions.get(project_id, [])]
                },
            )
            replace_projection(
                state.asset_lanes,
                quality_loop_repository.load_asset_lanes(),
            )

            persisted_runs, persisted_run_details = quality_loop_repository.load_runs()
            replace_projection(state.runs, persisted_runs)
            replace_projection(state.run_details, persisted_run_details)
            persisted_approvals, persisted_approval_details = (
                quality_loop_repository.load_approvals()
            )
            replace_projection(state.approvals, persisted_approvals)
            replace_projection(state.approval_details, persisted_approval_details)

            replace_projection(
                state.knowledge_objects,
                system_image_repository.load_knowledge_objects(),
            )
            replace_projection(
                state.raw_assets,
                system_image_repository.load_raw_assets(),
            )
            replace_projection(
                state.raw_asset_chunks,
                system_image_repository.load_raw_asset_chunks(),
            )
            replace_projection(
                state.baselines,
                system_image_repository.load_baselines(),
            )
            replace_projection(
                state.context_relationships,
                system_image_repository.load_context_relationships(),
            )
            replace_projection(
                state.context_object_overlays,
                system_image_repository.load_context_object_overlays(),
            )
            replace_projection(
                state.quality_metric_snapshots,
                system_image_repository.load_quality_metric_snapshots(),
            )
            replace_projection(
                state.embedding_records,
                system_image_repository.load_embedding_records(),
            )
            replace_projection(
                state.retrieval_runs,
                system_image_repository.load_retrieval_runs(),
            )
            replace_projection(
                state.rerank_records,
                system_image_repository.load_rerank_records(),
            )
            replace_projection(
                state.task_contexts,
                system_image_repository.load_task_contexts(),
            )
            replace_projection(
                state.quality_profiles,
                system_image_repository.load_quality_profiles(),
            )

            replace_projection(
                state.quality_asset_packs,
                quality_loop_repository.load_quality_asset_packs(),
            )
            replace_projection(
                state.execution_evidence,
                quality_loop_repository.load_execution_evidence(),
            )
            replace_projection(
                state.failure_reports,
                quality_loop_repository.load_failure_reports(),
            )
            replace_projection(
                state.release_decisions,
                quality_loop_repository.load_release_decisions(),
            )
            replace_projection(
                state.release_readiness,
                quality_loop_repository.load_release_readiness(),
            )
            replace_projection(
                state.merged_resolutions,
                quality_loop_repository.load_merged_resolutions(),
            )

    def refresh_project(self, project_id: str) -> None:
        with self._adapters.mutation_guard():
            self._refresh_project(project_id)

    def refresh_system_image(self, project_id: str) -> None:
        """Refresh only state owned or consumed by the system-image context."""

        with self._adapters.mutation_guard():
            state = self._state
            adapters = self._adapters
            project = adapters.project_repository.get_project(project_id)
            if project is not None:
                state.projects[project_id] = project
            state.versions[project_id] = adapters.project_repository.list_versions(
                project_id
            )
            active_version_id = (
                state.versions[project_id][0].id
                if state.versions[project_id]
                else None
            )
            state.us_items[project_id] = adapters.quality_loop_repository.list_us_items(
                project_id,
                active_version_id,
            )
            persisted_lanes = adapters.quality_loop_repository.list_asset_lanes(
                project_id
            )
            for us_item in state.us_items[project_id]:
                state.asset_lanes[us_item.id] = persisted_lanes.get(us_item.id, [])

            snapshot = adapters.system_image_repository.load_project_snapshot(project_id)
            state.knowledge_objects[project_id] = snapshot.knowledge_objects
            state.raw_assets[project_id] = snapshot.raw_assets
            state.raw_asset_chunks[project_id] = snapshot.raw_asset_chunks
            state.baselines[project_id] = snapshot.baselines
            state.context_relationships[project_id] = snapshot.relationships
            state.context_object_overlays[project_id] = snapshot.overlays
            state.quality_metric_snapshots[project_id] = snapshot.metric_snapshots
            state.embedding_records[project_id] = snapshot.embedding_records
            state.retrieval_runs[project_id] = snapshot.retrieval_runs
            state.rerank_records[project_id] = snapshot.rerank_records
            state.task_contexts[project_id] = snapshot.task_contexts
            state.quality_profiles[project_id] = snapshot.quality_profiles


    def _refresh_project(self, project_id: str) -> None:
        state = self._state
        project_repository = self._adapters.project_repository
        quality_loop_repository = self._adapters.quality_loop_repository
        system_image_repository = self._adapters.system_image_repository

        projects = {project.id: project for project in project_repository.load_projects()}
        if project_id in projects:
            state.projects[project_id] = projects[project_id]

        persisted_versions = project_repository.load_versions()
        state.versions[project_id] = persisted_versions.get(project_id, [])

        active_version_id = (
            state.versions[project_id][0].id
            if state.versions[project_id]
            else None
        )
        state.us_items[project_id] = quality_loop_repository.list_us_items(
            project_id,
            active_version_id,
        )

        persisted_asset_lanes = quality_loop_repository.load_asset_lanes()
        for us_item in state.us_items[project_id]:
            state.asset_lanes[us_item.id] = persisted_asset_lanes.get(us_item.id, [])

        persisted_runs, run_details = quality_loop_repository.load_runs()
        state.runs[project_id] = persisted_runs.get(project_id, [])
        state.run_details.update(run_details)

        persisted_approvals, approval_details = quality_loop_repository.load_approvals()
        state.approvals[project_id] = persisted_approvals.get(project_id, [])
        state.approval_details.update(approval_details)

        state.knowledge_objects[project_id] = system_image_repository.load_knowledge_objects().get(project_id, [])
        state.raw_assets[project_id] = system_image_repository.load_raw_assets().get(project_id, [])
        state.raw_asset_chunks[project_id] = system_image_repository.load_raw_asset_chunks().get(project_id, [])
        state.baselines[project_id] = system_image_repository.load_baselines().get(project_id, [])
        state.context_relationships[project_id] = system_image_repository.load_context_relationships().get(project_id, [])
        state.context_object_overlays[project_id] = system_image_repository.load_context_object_overlays().get(project_id, [])
        state.quality_metric_snapshots[project_id] = system_image_repository.load_quality_metric_snapshots().get(project_id, [])
        state.embedding_records[project_id] = system_image_repository.load_embedding_records().get(project_id, [])
        state.retrieval_runs[project_id] = system_image_repository.load_retrieval_runs().get(project_id, [])
        state.rerank_records[project_id] = system_image_repository.load_rerank_records().get(project_id, [])
        state.task_contexts[project_id] = system_image_repository.load_task_contexts().get(project_id, [])
        state.quality_profiles[project_id] = system_image_repository.load_quality_profiles().get(project_id, [])

        persisted_quality_asset_packs = quality_loop_repository.load_quality_asset_packs()
        retained_quality_asset_packs = {
            pack_id: pack
            for pack_id, pack in state.quality_asset_packs.items()
            if pack.project_id != project_id
        }
        retained_quality_asset_packs.update(
            {
                pack_id: pack
                for pack_id, pack in persisted_quality_asset_packs.items()
                if pack.project_id == project_id
            }
        )
        state.quality_asset_packs.clear()
        state.quality_asset_packs.update(retained_quality_asset_packs)

        state.execution_evidence[project_id] = quality_loop_repository.load_execution_evidence().get(project_id, [])
        state.failure_reports[project_id] = quality_loop_repository.load_failure_reports().get(project_id, [])

        persisted_release_decisions = quality_loop_repository.load_release_decisions()
        retained_release_decisions = {
            decision_id: decision
            for decision_id, decision in state.release_decisions.items()
            if decision.project_id != project_id
        }
        retained_release_decisions.update(
            {
                decision_id: decision
                for decision_id, decision in persisted_release_decisions.items()
                if decision.project_id == project_id
            }
        )
        state.release_decisions.clear()
        state.release_decisions.update(retained_release_decisions)

        state.release_readiness.update(
            quality_loop_repository.load_release_readiness()
        )


class RepositoryBackedProjectReadModelProjection:
    """No-cache projection used by the production composition root.

    Project-facing query adapters read PostgreSQL on every request. A
    committed command therefore needs no process-local cache invalidation.
    Keeping this adapter behind the existing application port lets command
    use cases retain their refresh boundary without reintroducing mutable
    mirrors in the process-local composition facade.
    """

    def refresh_project(self, project_id: str) -> None:
        del project_id

    def refresh_system_image(self, project_id: str) -> None:
        del project_id


__all__ = [
    "CompatibilityProjectReadModelProjection",
    "ProjectReadModelProjectionAdapters",
    "ProjectReadModelProjectionState",
    "RepositoryBackedProjectReadModelProjection",
]
