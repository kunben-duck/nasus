from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

from apps.api.app.application.platform.read_model_refresh import (
    ProjectReadModelRefreshApplicationService,
)
from apps.api.app.infrastructure.platform import (
    CompatibilityProjectReadModelProjection,
    ProjectReadModelProjectionAdapters,
    ProjectReadModelProjectionState,
)


class RecordingProjection:
    def __init__(self) -> None:
        self.project_ids: list[str] = []

    def refresh_project(self, project_id: str) -> None:
        self.project_ids.append(project_id)


def test_read_model_refresh_delegates_to_projection_port() -> None:
    projection = RecordingProjection()
    service = ProjectReadModelRefreshApplicationService(projection)

    service.refresh_project("proj_1")

    assert projection.project_ids == ["proj_1"]


def test_compatibility_projection_replaces_only_requested_project_state() -> None:
    project = SimpleNamespace(id="proj_1")
    version = SimpleNamespace(id="version_1")
    us_item = SimpleNamespace(id="us_1")
    pack = SimpleNamespace(id="pack_1", project_id="proj_1")
    other_pack = SimpleNamespace(id="pack_other", project_id="proj_other")
    decision = SimpleNamespace(id="decision_1", project_id="proj_1")
    other_decision = SimpleNamespace(id="decision_other", project_id="proj_other")
    run_detail = SimpleNamespace(id="run_1")
    approval_detail = SimpleNamespace(id="approval_1")

    project_repository = MagicMock()
    project_repository.load_projects.return_value = [project]
    project_repository.load_versions.return_value = {"proj_1": [version]}

    quality_loop_repository = MagicMock()
    quality_loop_repository.list_us_items.return_value = [us_item]
    quality_loop_repository.load_asset_lanes.return_value = {"us_1": ["lane"]}
    quality_loop_repository.load_runs.return_value = (
        {"proj_1": ["run"]},
        {"run_1": run_detail},
    )
    quality_loop_repository.load_approvals.return_value = (
        {"proj_1": ["approval"]},
        {"approval_1": approval_detail},
    )
    quality_loop_repository.load_quality_asset_packs.return_value = {"pack_1": pack}
    quality_loop_repository.load_execution_evidence.return_value = {"proj_1": ["evidence"]}
    quality_loop_repository.load_failure_reports.return_value = {"proj_1": ["failure"]}
    quality_loop_repository.load_release_decisions.return_value = {
        "decision_1": decision
    }
    quality_loop_repository.load_release_readiness.return_value = {
        "version_1": "readiness"
    }

    system_image_repository = MagicMock()
    system_image_repository.load_knowledge_objects.return_value = {"proj_1": ["knowledge"]}
    system_image_repository.load_raw_assets.return_value = {"proj_1": ["source"]}
    system_image_repository.load_raw_asset_chunks.return_value = {"proj_1": ["chunk"]}
    system_image_repository.load_baselines.return_value = {"proj_1": ["baseline"]}
    system_image_repository.load_context_relationships.return_value = {
        "proj_1": ["relationship"]
    }
    system_image_repository.load_context_object_overlays.return_value = {
        "proj_1": ["overlay"]
    }
    system_image_repository.load_quality_metric_snapshots.return_value = {
        "proj_1": ["metric"]
    }
    system_image_repository.load_embedding_records.return_value = {
        "proj_1": ["embedding"]
    }
    system_image_repository.load_retrieval_runs.return_value = {
        "proj_1": ["retrieval"]
    }
    system_image_repository.load_rerank_records.return_value = {
        "proj_1": ["rerank"]
    }
    system_image_repository.load_task_contexts.return_value = {
        "proj_1": ["task_context"]
    }
    system_image_repository.load_quality_profiles.return_value = {
        "proj_1": ["quality_profile"]
    }

    state = ProjectReadModelProjectionState(
        projects={},
        versions=defaultdict(list),
        us_items=defaultdict(list),
        asset_lanes=defaultdict(list),
        runs=defaultdict(list),
        run_details={},
        approvals=defaultdict(list),
        approval_details={},
        knowledge_objects=defaultdict(list),
        raw_assets=defaultdict(list),
        raw_asset_chunks=defaultdict(list),
        baselines=defaultdict(list),
        context_relationships=defaultdict(list),
        context_object_overlays=defaultdict(list),
        quality_metric_snapshots=defaultdict(list),
        embedding_records=defaultdict(list),
        retrieval_runs=defaultdict(list),
        rerank_records=defaultdict(list),
        task_contexts=defaultdict(list),
        quality_profiles=defaultdict(list),
        quality_asset_packs={
            "stale_pack": SimpleNamespace(project_id="proj_1"),
            "pack_other": other_pack,
        },
        execution_evidence=defaultdict(list),
        failure_reports=defaultdict(list),
        release_decisions={
            "stale_decision": SimpleNamespace(project_id="proj_1"),
            "decision_other": other_decision,
        },
        release_readiness={},
    )

    quality_asset_pack_projection = state.quality_asset_packs
    CompatibilityProjectReadModelProjection(
        state,
        ProjectReadModelProjectionAdapters(
            project_repository=project_repository,
            quality_loop_repository=quality_loop_repository,
            system_image_repository=system_image_repository,
            mutation_guard=nullcontext,
        ),
    ).refresh_project("proj_1")

    assert state.projects["proj_1"] is project
    assert state.versions["proj_1"] == [version]
    assert state.us_items["proj_1"] == [us_item]
    quality_loop_repository.list_us_items.assert_called_once_with(
        "proj_1",
        "version_1",
    )
    assert state.asset_lanes["us_1"] == ["lane"]
    assert state.run_details["run_1"] is run_detail
    assert state.approval_details["approval_1"] is approval_detail
    assert state.quality_asset_packs is quality_asset_pack_projection
    assert set(state.quality_asset_packs) == {"pack_1", "pack_other"}
    assert set(state.release_decisions) == {"decision_1", "decision_other"}
    assert state.release_readiness["version_1"] == "readiness"


def test_system_image_projection_uses_project_scoped_repository_queries() -> None:
    project = SimpleNamespace(id="proj_1")
    version = SimpleNamespace(id="version_1")
    us_item = SimpleNamespace(id="us_1")
    snapshot = SimpleNamespace(
        knowledge_objects=["knowledge"],
        raw_assets=["source"],
        raw_asset_chunks=["chunk"],
        baselines=["baseline"],
        relationships=["relationship"],
        overlays=["overlay"],
        metric_snapshots=["metric"],
        embedding_records=["embedding"],
        retrieval_runs=["retrieval"],
        rerank_records=["rerank"],
        task_contexts=["task_context"],
        quality_profiles=["quality_profile"],
    )
    project_repository = MagicMock()
    project_repository.get_project.return_value = project
    project_repository.list_versions.return_value = [version]
    quality_loop_repository = MagicMock()
    quality_loop_repository.list_us_items.return_value = [us_item]
    quality_loop_repository.list_asset_lanes.return_value = {"us_1": ["lane"]}
    system_image_repository = MagicMock()
    system_image_repository.load_project_snapshot.return_value = snapshot
    state = ProjectReadModelProjectionState(
        projects={},
        versions=defaultdict(list),
        us_items=defaultdict(list),
        asset_lanes=defaultdict(list),
        runs=defaultdict(list),
        run_details={},
        approvals=defaultdict(list),
        approval_details={},
        knowledge_objects=defaultdict(list),
        raw_assets=defaultdict(list),
        raw_asset_chunks=defaultdict(list),
        baselines=defaultdict(list),
        context_relationships=defaultdict(list),
        context_object_overlays=defaultdict(list),
        quality_metric_snapshots=defaultdict(list),
        embedding_records=defaultdict(list),
        retrieval_runs=defaultdict(list),
        rerank_records=defaultdict(list),
        task_contexts=defaultdict(list),
        quality_profiles=defaultdict(list),
        quality_asset_packs={},
        execution_evidence=defaultdict(list),
        failure_reports=defaultdict(list),
        release_decisions={},
        release_readiness={},
    )

    CompatibilityProjectReadModelProjection(
        state,
        ProjectReadModelProjectionAdapters(
            project_repository=project_repository,
            quality_loop_repository=quality_loop_repository,
            system_image_repository=system_image_repository,
            mutation_guard=nullcontext,
        ),
    ).refresh_system_image("proj_1")

    assert state.projects["proj_1"] is project
    assert state.versions["proj_1"] == [version]
    assert state.us_items["proj_1"] == [us_item]
    quality_loop_repository.list_us_items.assert_called_once_with(
        "proj_1",
        "version_1",
    )
    assert state.asset_lanes["us_1"] == ["lane"]
    assert state.raw_assets["proj_1"] == ["source"]
    assert state.quality_profiles["proj_1"] == ["quality_profile"]
    system_image_repository.load_project_snapshot.assert_called_once_with("proj_1")
    quality_loop_repository.load_runs.assert_not_called()
