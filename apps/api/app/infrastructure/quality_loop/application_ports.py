from __future__ import annotations

from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.quality_loop.quality_models import (
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ...application.quality_loop.ports import QualityLoopConversationScope
from ...application.system_image.system_image_models import QualityProfile, TaskContext
from .workspace_dependencies import (
    QualityLoopProjectionState,
    QualityLoopWorkspaceAdapters,
)


class LegacyProjectVersionWorkspace:
    """Bridge quality-loop onboarding ports to transitional projections.

    Application use cases receive detached model copies and must explicitly
    save mutations. Compatibility dictionaries and repository fan-out remain
    an infrastructure concern until the facade is removed.
    """

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def initialize_project(self, project: ProjectCard) -> None:
        stored_project = project.model_copy(deep=True)
        self._state.projects[project.id] = stored_project
        self._state.versions[project.id] = []
        self._state.us_items[project.id] = []
        self._state.runs[project.id] = []
        self._state.approvals[project.id] = []
        self._state.knowledge_objects[project.id] = []
        self._adapters.project_repository.upsert_project(stored_project)
        self._adapters.project_repository.replace_versions(project.id, [])
        self._adapters.project_repository.replace_us_items(project.id, None, [])
        self._adapters.project_repository.replace_runs(project.id, [])
        self._adapters.project_repository.replace_approvals(project.id, [])
        self._adapters.project_repository.replace_knowledge_objects(project.id, [])
        self._adapters.ensure_system_image_state(project.id, ready=False)
        self._adapters.grant_project_creator(project.id)
        self._adapters.get_or_create_conversation(
            "project",
            project.id,
            project.name,
        )

    def has_project(self, project_id: str) -> bool:
        return bool(project_id) and project_id in self._state.projects

    def get_project(self, project_id: str) -> ProjectCard:
        return self._state.projects[project_id].model_copy(deep=True)

    def save_project(self, project: ProjectCard) -> None:
        stored_project = project.model_copy(deep=True)
        self._state.projects[project.id] = stored_project
        self._adapters.project_repository.upsert_project(stored_project)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return [
            version.model_copy(deep=True)
            for version in self._state.versions.get(project_id, [])
        ]

    def replace_versions(
        self,
        project_id: str,
        versions: list[VersionSummary],
    ) -> None:
        stored_versions = [
            version.model_copy(deep=True)
            for version in versions
        ]
        self._state.versions[project_id] = stored_versions
        self._adapters.project_repository.replace_versions(
            project_id,
            stored_versions,
        )

    def prepend_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        stored_version = version.model_copy(deep=True)
        self._state.versions.setdefault(project_id, []).insert(0, stored_version)
        self._adapters.project_repository.prepend_version(
            project_id,
            stored_version,
        )

    def save_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        stored_version = version.model_copy(deep=True)
        versions = self._state.versions.setdefault(project_id, [])
        self._state.versions[project_id] = [
            stored_version if item.id == version.id else item
            for item in versions
        ]
        if all(item.id != version.id for item in versions):
            self._state.versions[project_id].insert(0, stored_version)
        self._adapters.project_repository.save_version(
            project_id,
            stored_version,
        )

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        if version_id is not None:
            return [
                item.model_copy(deep=True)
                for item in self._adapters.project_repository.list_us_items(
                    project_id,
                    version_id,
                )
            ]
        return [
            item.model_copy(deep=True)
            for item in self._state.us_items.get(project_id, [])
        ]

    def replace_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        stored_items = [item.model_copy(deep=True) for item in items]
        self._adapters.project_repository.replace_us_items(
            project_id,
            version_id,
            stored_items,
        )
        active_version = next(
            iter(self._state.versions.get(project_id, [])),
            None,
        )
        if version_id is None or (
            active_version is not None and active_version.id == version_id
        ):
            self._state.us_items[project_id] = stored_items

    def save_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        stored_items = [item.model_copy(deep=True) for item in items]
        self._adapters.quality_loop_repository.upsert_us_items(
            project_id,
            version_id,
            stored_items,
        )
        active_version = next(
            iter(self._state.versions.get(project_id, [])),
            None,
        )
        if version_id is None or (
            active_version is not None and active_version.id == version_id
        ):
            self._state.us_items[project_id] = stored_items

    def save_us_item(
        self,
        project_id: str,
        version_id: str | None,
        item: USItem,
    ) -> None:
        stored_item = item.model_copy(deep=True)
        self._adapters.quality_loop_repository.upsert_us_item(
            project_id,
            version_id,
            stored_item,
        )
        items = self._state.us_items.setdefault(project_id, [])
        self._state.us_items[project_id] = [
            stored_item if candidate.id == item.id else candidate
            for candidate in items
        ]

    def save_release_readiness(
        self,
        project_id: str,
        readiness: ReleaseReadiness,
    ) -> None:
        stored_readiness = readiness.model_copy(deep=True)
        self._state.release_readiness[readiness.version_id] = stored_readiness
        self._adapters.project_repository.upsert_release_readiness(
            project_id,
            stored_readiness,
        )

    def conversation_project_id(self, conversation_id: str | None) -> str | None:
        if not conversation_id:
            return None
        conversation = self._state.conversations.get(conversation_id)
        if conversation is None:
            return None
        if conversation.project_id:
            return conversation.project_id
        if conversation.space_type == "project":
            return conversation.space_id
        return None

    def has_indexed_system_image_evidence(self, project_id: str) -> bool:
        project = self._state.projects.get(project_id)
        return bool(
            project
            and project.system_image_status in {"indexed", "ready"}
            and self._state.raw_assets.get(project_id)
        )


class LegacyQualityLoopContextWorkspace:
    """Read detached quality-loop context from transitional projections."""

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        return [
            context.model_copy(deep=True)
            for context in self._state.task_contexts.get(project_id, [])
        ]

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        return [
            profile.model_copy(deep=True)
            for profile in self._state.quality_profiles.get(project_id, [])
        ]

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        pack = self._state.quality_asset_packs.get(f"qap_{project_id}_{us_id}")
        return pack.model_copy(deep=True) if pack is not None else None

    def list_quality_asset_packs(self, project_id: str) -> list[QualityAssetPack]:
        return [
            pack.model_copy(deep=True)
            for pack in self._state.quality_asset_packs.values()
            if pack.project_id == project_id
        ]

    def list_us_items(self, project_id: str) -> list[USItem]:
        return [
            item.model_copy(deep=True)
            for item in self._state.us_items.get(project_id, [])
        ]

    def project_id_for_us(self, us_id: str) -> str | None:
        for project_id, items in self._state.us_items.items():
            if any(item.id == us_id for item in items):
                return project_id
        return None

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return [
            lane.model_copy(deep=True)
            for lane in self._state.asset_lanes.get(us_id, [])
        ]


class LegacyQualityLoopScopeWorkspace:
    """Resolve ownership facts from transitional quality-loop projections."""

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def conversation_scope(
        self,
        conversation_id: str | None,
    ) -> QualityLoopConversationScope | None:
        if not conversation_id:
            return None
        conversation = self._state.conversations.get(conversation_id)
        if conversation is None:
            return None
        return QualityLoopConversationScope(
            project_id=conversation.project_id,
            us_id=conversation.us_id,
            space_type=conversation.space_type,
            space_id=conversation.space_id,
        )

    def project_id_for_us(self, us_id: str) -> str | None:
        for project_id, items in self._state.us_items.items():
            if any(item.id == us_id for item in items):
                return project_id
        return None

    def first_us_id(self, project_id: str) -> str | None:
        first_us = next(iter(self._state.us_items.get(project_id, [])), None)
        return first_us.id if first_us is not None else None

    def project_id_for_run(self, run_id: str) -> str | None:
        for project_id, runs in self._state.runs.items():
            if any(item.id == run_id for item in runs):
                return project_id
        return None

    def list_run_details(self, project_id: str) -> list[RunDetail]:
        return [
            self._state.run_details[run.id].model_copy(deep=True)
            for run in self._state.runs.get(project_id, [])
            if run.id in self._state.run_details
        ]

    def us_id_for_run_evidence(
        self,
        project_id: str,
        run_id: str,
    ) -> str | None:
        return next(
            (
                item.us_id
                for item in self._state.execution_evidence.get(project_id, [])
                if item.run_id == run_id and item.us_id
            ),
            None,
        )


class LegacyQualityAssetProgressWorkspace:
    """Persist lane and US progress while maintaining migration projections."""

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return [
            lane.model_copy(deep=True)
            for lane in self._state.asset_lanes.get(us_id, [])
        ]

    def ensure_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        stored_lanes = self._state.asset_lanes.setdefault(us_id, [])
        known_ids = {lane.id for lane in stored_lanes}
        missing = [
            lane.model_copy(deep=True)
            for lane in lanes
            if lane.id not in known_ids
        ]
        if not missing:
            return
        stored_lanes.extend(missing)
        self._adapters.quality_loop_repository.ensure_asset_lanes(
            project_id,
            us_id,
            missing,
        )

    def save_asset_lane(
        self,
        project_id: str,
        us_id: str,
        lane: AssetLane,
    ) -> None:
        stored_lane = lane.model_copy(deep=True)
        lanes = self._state.asset_lanes.setdefault(us_id, [])
        self._state.asset_lanes[us_id] = [
            stored_lane if item.id == lane.id else item
            for item in lanes
        ]
        if all(item.id != lane.id for item in lanes):
            self._state.asset_lanes[us_id].append(stored_lane)
        self._adapters.quality_loop_repository.upsert_asset_lane(
            project_id,
            us_id,
            stored_lane,
        )

    def get_us_item(self, project_id: str, us_id: str) -> USItem | None:
        item = next(
            (
                candidate
                for candidate in self._state.us_items.get(project_id, [])
                if candidate.id == us_id
            ),
            None,
        )
        return item.model_copy(deep=True) if item is not None else None

    def save_us_item(
        self,
        project_id: str,
        item: USItem,
    ) -> None:
        stored_item = item.model_copy(deep=True)
        items = self._state.us_items.setdefault(project_id, [])
        self._state.us_items[project_id] = [
            stored_item if candidate.id == item.id else candidate
            for candidate in items
        ]
        if all(candidate.id != item.id for candidate in items):
            self._state.us_items[project_id].append(stored_item)
        self._adapters.quality_loop_repository.upsert_us_item_preserving_version(
            project_id,
            stored_item,
        )


class LegacyQualityAssetPackWorkspace:
    """Persist QualityAssetPack aggregates and maintain migration projections."""

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        pack = self._state.quality_asset_packs.get(
            f"qap_{project_id}_{us_id}"
        )
        return pack.model_copy(deep=True) if pack is not None else None

    def save_quality_asset_pack(self, pack: QualityAssetPack) -> None:
        stored_pack = pack.model_copy(deep=True)
        self._state.quality_asset_packs[pack.id] = stored_pack
        self._adapters.project_repository.upsert_quality_asset_pack(stored_pack)


class LegacyQualityRunWorkspace:
    """Translate runner persistence ports to durable quality-loop storage."""

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def us_title(self, project_id: str, us_id: str) -> str | None:
        with self._adapters.mutation_guard():
            item = next(
                (
                    candidate
                    for candidate in self._state.us_items.get(project_id, [])
                    if candidate.id == us_id
                ),
                None,
            )
            return item.title if item is not None else None

    def save_run_detail(self, project_id: str, run: RunDetail) -> None:
        stored_run = run.model_copy(deep=True)
        with self._adapters.mutation_guard():
            existing_details = [
                self._state.run_details[item.id].model_copy(deep=True)
                for item in self._state.runs.get(project_id, [])
                if item.id != run.id and item.id in self._state.run_details
            ]
            details = [stored_run, *existing_details]
            self._adapters.quality_loop_repository.replace_runs(
                project_id,
                details,
            )
            self._state.run_details[run.id] = stored_run
            self._state.runs[project_id] = [
                RunSummary(
                    id=item.id,
                    status=item.status,
                    channel=item.channel,
                    title=item.title,
                    summary=item.summary,
                    started_at=item.started_at,
                )
                for item in details
            ]

    def replace_run_evidence(
        self,
        project_id: str,
        run_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None:
        stored_evidence = [item.model_copy(deep=True) for item in evidence]
        with self._adapters.mutation_guard():
            existing = [
                item.model_copy(deep=True)
                for item in self._state.execution_evidence.get(project_id, [])
                if item.run_id != run_id
            ]
            merged = [*stored_evidence, *existing]
            self._adapters.quality_loop_repository.replace_execution_evidence(
                project_id,
                merged,
            )
            self._state.execution_evidence[project_id] = merged


class LegacyQualityFailureWorkspace:
    """Persist failure analysis atomically and maintain compatibility views."""

    def __init__(
        self,
        state: QualityLoopProjectionState,
        adapters: QualityLoopWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        reports = self._adapters.quality_loop_repository.list_failure_reports(
            project_id
        )
        detached = [item.model_copy(deep=True) for item in reports]
        with self._adapters.mutation_guard():
            self._state.failure_reports[project_id] = [
                item.model_copy(deep=True) for item in detached
            ]
        return detached

    def save_failure_analysis(
        self,
        project_id: str,
        run: RunDetail,
        reports: list[FailureReport],
    ) -> None:
        stored_run = run.model_copy(deep=True)
        stored_reports = [item.model_copy(deep=True) for item in reports]
        with self._adapters.mutation_guard():
            existing_details = [
                self._state.run_details[item.id].model_copy(deep=True)
                for item in self._state.runs.get(project_id, [])
                if item.id != run.id and item.id in self._state.run_details
            ]
            details = [stored_run, *existing_details]
            self._adapters.quality_loop_repository.replace_failure_analysis(
                project_id,
                details,
                stored_reports,
            )
            self._state.run_details[run.id] = stored_run
            self._state.runs[project_id] = [
                RunSummary(
                    id=item.id,
                    status=item.status,
                    channel=item.channel,
                    title=item.title,
                    summary=item.summary,
                    started_at=item.started_at,
                )
                for item in details
            ]
            self._state.failure_reports[project_id] = stored_reports


__all__ = [
    "LegacyProjectVersionWorkspace",
    "LegacyQualityAssetPackWorkspace",
    "LegacyQualityAssetProgressWorkspace",
    "LegacyQualityLoopContextWorkspace",
    "LegacyQualityFailureWorkspace",
    "LegacyQualityRunWorkspace",
    "LegacyQualityLoopScopeWorkspace",
]
