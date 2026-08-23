from __future__ import annotations

from collections.abc import Callable, MutableMapping, MutableSequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from ...application.platform.demo_seed_ports import DemoSeedBaseline


class DemoProjectRepositoryPort(Protocol):
    def get_project(self, project_id: str) -> Any | None: ...

    def list_versions(self, project_id: str) -> list[Any]: ...

    def upsert_project(self, project: Any) -> None: ...

    def replace_versions(self, project_id: str, versions: list[Any]) -> None: ...


class DemoQualityLoopRepositoryPort(Protocol):
    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[Any]: ...

    def list_asset_lanes(self, project_id: str) -> dict[str, list[Any]]: ...

    def list_runs(self, project_id: str) -> list[Any]: ...

    def list_approvals(self, project_id: str) -> list[Any]: ...

    def get_release_readiness(self, version_id: str) -> Any | None: ...

    def replace_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[Any],
    ) -> None: ...

    def replace_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[Any],
    ) -> None: ...

    def replace_runs(self, project_id: str, runs: list[Any]) -> None: ...

    def replace_approvals(self, project_id: str, approvals: list[Any]) -> None: ...

    def upsert_release_readiness(self, project_id: str, readiness: Any) -> None: ...


class DemoSystemImageRepositoryPort(Protocol):
    def load_project_snapshot(self, project_id: str) -> Any: ...

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[Any],
    ) -> None: ...

    def replace_system_image(self, project_id: str, **snapshot: Any) -> None: ...


@dataclass(frozen=True)
class DemoSeedProjectionState:
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
    baselines: MutableMapping[str, list[Any]]
    context_relationships: MutableMapping[str, list[Any]]
    quality_metric_snapshots: MutableMapping[str, list[Any]]
    documentation_entries: MutableSequence[Any]
    release_readiness: MutableMapping[str, Any]


@dataclass(frozen=True)
class DemoSeedWorkspaceAdapters:
    project_repository: DemoProjectRepositoryPort
    quality_loop_repository: DemoQualityLoopRepositoryPort
    system_image_repository: DemoSystemImageRepositoryPort
    get_or_create_conversation: Callable[[str, str, str], Any]
    mutation_guard: Callable[[], AbstractContextManager[None]]


class CompatibilityDemoSeedWorkspace:
    """Local-only adapter for deterministic seed facts and persistence."""

    def __init__(
        self,
        state: DemoSeedProjectionState,
        adapters: DemoSeedWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def seed_baseline(self, baseline: DemoSeedBaseline) -> None:
        with self._adapters.mutation_guard():
            state = self._state
            adapters = self._adapters
            project = state.projects.get(baseline.project.id)
            if project is None:
                project = baseline.project
                state.projects[project.id] = project
                state.versions[project.id] = [baseline.version]
                state.us_items[project.id] = list(baseline.us_items)
                adapters.project_repository.upsert_project(project)
                adapters.project_repository.replace_versions(
                    project.id,
                    [baseline.version],
                )
                adapters.quality_loop_repository.replace_us_items(
                    project.id,
                    baseline.version.id,
                    list(baseline.us_items),
                )

            version = (
                state.versions[project.id][0]
                if state.versions[project.id]
                else baseline.version
            )
            if not state.us_items[project.id]:
                state.us_items[project.id] = list(baseline.us_items)
            lanes = state.asset_lanes.get("us_123") or list(baseline.asset_lanes)
            runs = state.runs.get(project.id) or [baseline.run_summary]
            approvals = state.approvals.get(project.id) or [baseline.approval_summary]
            run_detail = state.run_details.get(baseline.run_detail.id) or baseline.run_detail
            approval_detail = (
                state.approval_details.get(baseline.approval_detail.id)
                or baseline.approval_detail
            )
            knowledge_objects = (
                state.knowledge_objects.get(project.id)
                or list(baseline.knowledge_objects)
            )
            readiness = state.release_readiness.get(version.id)
            if readiness is None:
                readiness = baseline.release_readiness.model_copy(
                    update={"version_id": version.id}
                )

            state.run_details[run_detail.id] = run_detail
            state.approval_details[approval_detail.id] = approval_detail
            state.knowledge_objects[project.id] = knowledge_objects
            state.raw_assets[project.id] = list(baseline.system_image.sources)
            state.baselines[project.id] = list(baseline.system_image.baselines)
            state.context_relationships[project.id] = list(
                baseline.system_image.relationships
            )
            state.quality_metric_snapshots[project.id] = list(
                baseline.system_image.metric_snapshots
            )
            state.documentation_entries.clear()
            state.documentation_entries.extend(baseline.documentation_entries)
            state.release_readiness[version.id] = readiness
            state.asset_lanes["us_123"] = lanes
            state.runs[project.id] = runs
            state.approvals[project.id] = approvals

            adapters.quality_loop_repository.replace_asset_lanes(
                project.id,
                "us_123",
                lanes,
            )
            adapters.quality_loop_repository.replace_runs(
                project.id,
                [run_detail],
            )
            adapters.quality_loop_repository.replace_approvals(
                project.id,
                [approval_detail],
            )
            adapters.system_image_repository.replace_knowledge_objects(
                project.id,
                knowledge_objects,
            )
            adapters.system_image_repository.replace_system_image(
                project.id,
                sources=list(baseline.system_image.sources),
                chunks=[],
                baselines=list(baseline.system_image.baselines),
                relationships=list(baseline.system_image.relationships),
                overlays=[],
                metric_snapshots=list(baseline.system_image.metric_snapshots),
                embedding_records=[],
                retrieval_runs=[],
                rerank_records=[],
                task_contexts=[],
                quality_profiles=[],
            )
            adapters.quality_loop_repository.upsert_release_readiness(
                project.id,
                readiness,
            )

    def ensure_conversation(
        self,
        space_type: str,
        space_id: str,
        title: str,
    ) -> None:
        self._adapters.get_or_create_conversation(space_type, space_id, title)


class SQLAlchemyDemoSeedWorkspace:
    """Persist optional local seed facts without process-local projections."""

    def __init__(
        self,
        *,
        project_repository: DemoProjectRepositoryPort,
        quality_loop_repository: DemoQualityLoopRepositoryPort,
        system_image_repository: DemoSystemImageRepositoryPort,
        get_or_create_conversation: Callable[[str, str, str], Any],
    ) -> None:
        self._projects = project_repository
        self._quality_loop = quality_loop_repository
        self._system_image = system_image_repository
        self._get_or_create_conversation = get_or_create_conversation

    def seed_baseline(self, baseline: DemoSeedBaseline) -> None:
        project = self._projects.get_project(baseline.project.id)
        if project is None:
            project = baseline.project
            self._projects.upsert_project(project)

        versions = self._projects.list_versions(project.id)
        if not versions:
            versions = [baseline.version]
            self._projects.replace_versions(project.id, versions)
        version = versions[0]

        us_items = self._quality_loop.list_us_items(project.id, version.id)
        if not us_items:
            us_items = list(baseline.us_items)
            self._quality_loop.replace_us_items(project.id, version.id, us_items)

        lanes = self._quality_loop.list_asset_lanes(project.id)
        first_us_id = us_items[0].id if us_items else baseline.us_items[0].id
        if not lanes.get(first_us_id):
            self._quality_loop.replace_asset_lanes(
                project.id,
                first_us_id,
                list(baseline.asset_lanes),
            )
        if not self._quality_loop.list_runs(project.id):
            self._quality_loop.replace_runs(project.id, [baseline.run_detail])
        if not self._quality_loop.list_approvals(project.id):
            self._quality_loop.replace_approvals(
                project.id,
                [baseline.approval_detail],
            )

        snapshot = self._system_image.load_project_snapshot(project.id)
        knowledge_objects = snapshot.knowledge_objects or list(
            baseline.knowledge_objects
        )
        if not snapshot.knowledge_objects:
            self._system_image.replace_knowledge_objects(
                project.id,
                knowledge_objects,
            )
        if not snapshot.raw_assets and not snapshot.baselines:
            self._system_image.replace_system_image(
                project.id,
                sources=list(baseline.system_image.sources),
                chunks=[],
                baselines=list(baseline.system_image.baselines),
                relationships=list(baseline.system_image.relationships),
                overlays=[],
                metric_snapshots=list(baseline.system_image.metric_snapshots),
                embedding_records=[],
                retrieval_runs=[],
                rerank_records=[],
                task_contexts=[],
                quality_profiles=[],
                knowledge_objects=knowledge_objects,
            )

        readiness = self._quality_loop.get_release_readiness(version.id)
        if readiness is None:
            readiness = baseline.release_readiness.model_copy(
                update={"version_id": version.id}
            )
            self._quality_loop.upsert_release_readiness(project.id, readiness)

    def ensure_conversation(
        self,
        space_type: str,
        space_id: str,
        title: str,
    ) -> None:
        self._get_or_create_conversation(space_type, space_id, title)


__all__ = [
    "CompatibilityDemoSeedWorkspace",
    "DemoSeedProjectionState",
    "DemoSeedWorkspaceAdapters",
    "SQLAlchemyDemoSeedWorkspace",
]
