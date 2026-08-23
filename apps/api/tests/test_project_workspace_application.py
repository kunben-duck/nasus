from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from apps.api.app.application.platform.project_models import (
    ProjectCard,
    ProjectCreateRequest,
    VersionSummary,
)
from apps.api.app.application.platform.project_workspace import (
    ProjectWorkspaceApplicationService,
)
from apps.api.app.application.platform.project_workspace_ports import (
    ProjectWorkspaceSnapshot,
)
from apps.api.app.application.quality_loop.quality_models import AssetLane, USItem
from apps.api.app.infrastructure.platform.project_workspace_read_model import (
    SQLAlchemyProjectWorkspaceReadModel,
)


def _project(project_id: str = "proj_checkout") -> ProjectCard:
    return ProjectCard(
        id=project_id,
        name="Checkout",
        code="CHK",
        summary="Checkout quality",
        status="active",
        risk="medium",
        progress=40,
        active_version="2026.Q3",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="ready",
    )


def _version() -> VersionSummary:
    return VersionSummary(
        id="version_q3",
        name="2026.Q3",
        status="active",
        branch_name="release/2026-q3",
        us_total=1,
        us_closed=0,
        pending_runs=0,
        pending_approvals=0,
    )


class RecordingReadModel:
    def __init__(self, snapshot: ProjectWorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.workspace_reads: list[str] = []

    def list_projects(self):
        return [self.snapshot.project]

    def get_project(self, project_id: str):
        return self.snapshot.project if project_id == self.snapshot.project.id else None

    def load_workspace(self, project_id: str):
        self.workspace_reads.append(project_id)
        return self.snapshot if project_id == self.snapshot.project.id else None

    def get_run_detail(self, project_id: str, run_id: str):
        return SimpleNamespace(id=run_id, project_id=project_id)

    def get_approval_detail(self, project_id: str, approval_id: str):
        return SimpleNamespace(id=approval_id, project_id=project_id)


def _service(snapshot: ProjectWorkspaceSnapshot):
    read_model = RecordingReadModel(snapshot)
    authorization = Mock()
    authorization.visible_project_ids.return_value = {snapshot.project.id}
    tools = Mock()
    tools.create_tool_invocation = AsyncMock()
    conversations = Mock()
    service = ProjectWorkspaceApplicationService(
        read_model=read_model,
        authorization=authorization,
        tool_invocations=tools,
        conversations=conversations,
    )
    return service, read_model, authorization, tools, conversations


def test_workspace_query_reads_one_durable_snapshot_without_compatibility_refresh() -> None:
    us = USItem(
        id="us_checkout",
        title="Checkout",
        owner="QA",
        status="analysis",
        risk="medium",
        progress=20,
        next_action="Generate cases",
    )
    lane = AssetLane(
        id="lane_scenarios",
        label="Scenarios",
        status="completed",
        summary="Scenarios complete",
        updated_at="2026-08-08T00:00:00Z",
    )
    snapshot = ProjectWorkspaceSnapshot(
        project=_project(),
        versions=[_version()],
        us_items=[us],
        asset_lanes={us.id: [lane]},
    )
    service, read_model, authorization, _tools, _conversations = _service(snapshot)

    response = service.get_project_workspace(snapshot.project.id)

    assert response.project.id == snapshot.project.id
    assert response.current_version_id == "version_q3"
    assert response.quality_loop_state.status == "in_progress"
    assert read_model.workspace_reads == [snapshot.project.id]
    authorization.require_project_access.assert_called_once_with(snapshot.project.id)


def test_project_creation_returns_the_postgresql_read_model_from_the_tool_result() -> None:
    snapshot = ProjectWorkspaceSnapshot(project=_project())
    service, read_model, _authorization, tools, _conversations = _service(snapshot)
    tools.create_tool_invocation.return_value = SimpleNamespace(
        status="completed",
        summary="created",
        result=SimpleNamespace(object_refs=[f"project:{snapshot.project.id}"]),
    )

    project = asyncio.run(service.create_project(ProjectCreateRequest(name=" Checkout ")))

    assert project == snapshot.project
    invocation = tools.create_tool_invocation.await_args.args[0]
    assert invocation.tool_id == "project.create"
    assert invocation.input == {"name": "Checkout"}
    assert read_model.get_project(snapshot.project.id) == snapshot.project


def test_release_readiness_is_optional_until_a_project_has_been_assessed() -> None:
    snapshot = ProjectWorkspaceSnapshot(project=_project())
    service, _read_model, authorization, _tools, _conversations = _service(snapshot)

    assert service.get_release_readiness(snapshot.project.id) is None
    authorization.require_project_access.assert_called_once_with(snapshot.project.id)


def test_sqlalchemy_workspace_adapter_composes_bounded_context_repositories() -> None:
    project_repository = Mock()
    quality_loop_repository = Mock()
    system_image_repository = Mock()
    project_repository.get_project.return_value = _project()
    project_repository.list_versions.return_value = [_version()]
    quality_loop_repository.list_us_items.return_value = []
    quality_loop_repository.list_asset_lanes.return_value = {}
    quality_loop_repository.list_runs.return_value = []
    quality_loop_repository.list_approvals.return_value = []
    quality_loop_repository.list_quality_asset_packs.return_value = []
    quality_loop_repository.list_execution_evidence.return_value = []
    quality_loop_repository.list_failure_reports.return_value = []
    quality_loop_repository.list_release_decisions.return_value = []
    quality_loop_repository.get_release_readiness.return_value = None
    system_image_repository.list_task_contexts.return_value = []
    system_image_repository.list_quality_profiles.return_value = []
    adapter = SQLAlchemyProjectWorkspaceReadModel(
        project_repository,
        quality_loop_repository,
        system_image_repository,
    )

    snapshot = adapter.load_workspace("proj_checkout")

    assert snapshot is not None
    assert snapshot.project.id == "proj_checkout"
    assert snapshot.versions[0].id == "version_q3"
    quality_loop_repository.list_us_items.assert_called_once_with(
        "proj_checkout",
        "version_q3",
    )
    system_image_repository.list_task_contexts.assert_called_once_with("proj_checkout")


def test_sqlalchemy_workspace_adapter_does_not_query_child_contexts_for_missing_project() -> None:
    project_repository = Mock()
    quality_loop_repository = Mock()
    system_image_repository = Mock()
    project_repository.get_project.return_value = None
    adapter = SQLAlchemyProjectWorkspaceReadModel(
        project_repository,
        quality_loop_repository,
        system_image_repository,
    )

    assert adapter.load_workspace("missing") is None
    quality_loop_repository.list_us_items.assert_not_called()
    system_image_repository.list_task_contexts.assert_not_called()
