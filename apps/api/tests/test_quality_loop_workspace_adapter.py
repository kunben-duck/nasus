from __future__ import annotations

from collections import defaultdict
from threading import RLock
from unittest.mock import Mock

from apps.api.app.application.platform.project_models import ProjectCard
from apps.api.app.application.quality_loop.quality_models import QualityAssetPack
from apps.api.app.infrastructure.quality_loop import (
    LegacyProjectVersionWorkspace,
    LegacyQualityAssetPackWorkspace,
    QualityLoopProjectionState,
    QualityLoopWorkspaceAdapters,
)


def _projection_state() -> QualityLoopProjectionState:
    return QualityLoopProjectionState(
        projects={},
        versions=defaultdict(list),
        us_items=defaultdict(list),
        asset_lanes=defaultdict(list),
        quality_asset_packs={},
        runs=defaultdict(list),
        run_details={},
        execution_evidence=defaultdict(list),
        failure_reports=defaultdict(list),
        approvals=defaultdict(list),
        knowledge_objects=defaultdict(list),
        release_readiness={},
        conversations={},
        raw_assets=defaultdict(list),
        task_contexts=defaultdict(list),
        quality_profiles=defaultdict(list),
    )


def _workspace_adapters() -> QualityLoopWorkspaceAdapters:
    lock = RLock()
    return QualityLoopWorkspaceAdapters(
        project_repository=Mock(),
        quality_loop_repository=Mock(),
        mutation_guard=lambda: lock,
        ensure_system_image_state=Mock(),
        grant_project_creator=Mock(),
        get_or_create_conversation=Mock(),
    )


def test_project_workspace_operates_without_application_store() -> None:
    state = _projection_state()
    adapters = _workspace_adapters()
    workspace = LegacyProjectVersionWorkspace(state, adapters)
    project = ProjectCard(
        id="project_quality",
        name="Checkout",
        code="CHK",
        summary="Checkout quality",
        status="active",
        risk="medium",
        progress=0,
        active_version="",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="not_started",
    )

    workspace.initialize_project(project)

    assert workspace.get_project(project.id) == project
    assert state.projects[project.id] is not project
    assert state.versions[project.id] == []
    adapters.project_repository.upsert_project.assert_called_once()
    adapters.ensure_system_image_state.assert_called_once_with(
        project.id,
        ready=False,
    )
    adapters.grant_project_creator.assert_called_once_with(project.id)
    adapters.get_or_create_conversation.assert_called_once_with(
        "project",
        project.id,
        project.name,
    )


def test_quality_asset_pack_workspace_mutates_shared_projection_in_place() -> None:
    state = _projection_state()
    adapters = _workspace_adapters()
    workspace = LegacyQualityAssetPackWorkspace(state, adapters)
    projection_identity = id(state.quality_asset_packs)
    pack = QualityAssetPack(
        id="qap_project_quality_us_checkout",
        project_id="project_quality",
        us_id="us_checkout",
        updated_at="2026-07-30T00:00:00Z",
    )

    workspace.save_quality_asset_pack(pack)

    assert id(state.quality_asset_packs) == projection_identity
    assert workspace.get_quality_asset_pack(
        pack.project_id,
        pack.us_id,
    ) == pack
    assert state.quality_asset_packs[pack.id] is not pack
    adapters.project_repository.upsert_quality_asset_pack.assert_called_once()
