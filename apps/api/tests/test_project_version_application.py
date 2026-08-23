from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from apps.api.app.application.platform.project_models import (
    ProjectCard,
    VersionSummary,
)
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.application.quality_loop.project_versions import (
    ProjectVersionApplicationService,
)
from apps.api.app.application.quality_loop.version_context import (
    QualityLoopVersionContextApplicationService,
)
from apps.api.app.application.quality_loop.quality_models import (
    ReleaseReadiness,
    USItem,
)


@dataclass
class InMemoryProjectVersionWorkspace:
    projects: dict[str, ProjectCard] = field(default_factory=dict)
    versions: dict[str, list[VersionSummary]] = field(default_factory=dict)
    us_items: dict[str, list[USItem]] = field(default_factory=dict)
    version_us_items: dict[tuple[str, str | None], list[USItem]] = field(
        default_factory=dict
    )
    release_readiness: dict[str, ReleaseReadiness] = field(default_factory=dict)
    conversation_projects: dict[str, str] = field(default_factory=dict)
    indexed_projects: set[str] = field(default_factory=set)

    def initialize_project(self, project: ProjectCard) -> None:
        self.projects[project.id] = project.model_copy(deep=True)
        self.versions[project.id] = []
        self.us_items[project.id] = []

    def has_project(self, project_id: str) -> bool:
        return project_id in self.projects

    def get_project(self, project_id: str) -> ProjectCard:
        return self.projects[project_id].model_copy(deep=True)

    def save_project(self, project: ProjectCard) -> None:
        self.projects[project.id] = project.model_copy(deep=True)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return [
            version.model_copy(deep=True)
            for version in self.versions.get(project_id, [])
        ]

    def replace_versions(
        self,
        project_id: str,
        versions: list[VersionSummary],
    ) -> None:
        self.versions[project_id] = [
            version.model_copy(deep=True)
            for version in versions
        ]

    def prepend_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        self.versions.setdefault(project_id, []).insert(
            0,
            version.model_copy(deep=True),
        )

    def save_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        versions = self.versions.setdefault(project_id, [])
        self.versions[project_id] = [
            version.model_copy(deep=True) if item.id == version.id else item
            for item in versions
        ]
        if all(item.id != version.id for item in versions):
            self.versions[project_id].insert(0, version.model_copy(deep=True))

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        source = (
            self.version_us_items.get((project_id, version_id), [])
            if version_id is not None
            else self.us_items.get(project_id, [])
        )
        return [
            item.model_copy(deep=True)
            for item in source
        ]

    def replace_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        stored_items = [
            item.model_copy(deep=True)
            for item in items
        ]
        self.version_us_items[(project_id, version_id)] = stored_items
        active_version = next(iter(self.versions.get(project_id, [])), None)
        if version_id is None or (
            active_version is not None and active_version.id == version_id
        ):
            self.us_items[project_id] = stored_items

    def save_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        if version_id is not None:
            adopted_ids = {item.id for item in items}
            self.version_us_items[(project_id, None)] = [
                item
                for item in self.version_us_items.get((project_id, None), [])
                if item.id not in adopted_ids
            ]
        self.replace_us_items(project_id, version_id, items)

    def save_us_item(
        self,
        project_id: str,
        version_id: str | None,
        item: USItem,
    ) -> None:
        current = self.list_us_items(project_id, version_id)
        updated = [
            item.model_copy(deep=True) if candidate.id == item.id else candidate
            for candidate in current
        ]
        if all(candidate.id != item.id for candidate in current):
            updated.append(item.model_copy(deep=True))
        self.replace_us_items(project_id, version_id, updated)

    def save_release_readiness(
        self,
        project_id: str,
        readiness: ReleaseReadiness,
    ) -> None:
        del project_id
        self.release_readiness[readiness.version_id] = readiness.model_copy(
            deep=True
        )

    def conversation_project_id(self, conversation_id: str | None) -> str | None:
        if not conversation_id:
            return None
        return self.conversation_projects.get(conversation_id)

    def has_indexed_system_image_evidence(self, project_id: str) -> bool:
        return project_id in self.indexed_projects


class StubSystemImageOperations:
    def __init__(self) -> None:
        self.materialized_projects: list[str] = []

    async def materialize_context(self, project_id: str) -> None:
        self.materialized_projects.append(project_id)

    def normalize_source_specs(self, source_specs: Any) -> Any:
        return source_specs

    def register_sources(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("register_sources is not used by this test")

    def missing_source_types(self, project_id: str) -> list[str]:
        del project_id
        return []


class EmptyContextQueries:
    def current_task_context(
        self,
        project_id: str,
        us_id: str | None = None,
    ) -> None:
        del project_id, us_id
        return None

    def current_quality_profile(
        self,
        project_id: str,
        us_id: str | None = None,
    ) -> None:
        del project_id, us_id
        return None


def invocation(
    tool_id: str,
    *,
    conversation_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
) -> ToolInvocation:
    return ToolInvocation(
        id=f"inv_{tool_id}",
        conversation_id=conversation_id,
        tool_id=tool_id,
        status="pending",
        summary="test",
        input_payload=input_payload or {},
    )


def test_project_version_and_us_workflow_runs_only_through_ports() -> None:
    workspace = InMemoryProjectVersionWorkspace()
    system_image = StubSystemImageOperations()
    service = ProjectVersionApplicationService(
        workspace,
        system_image,
        EmptyContextQueries(),
    )

    project = service.create_project_record("Checkout Platform")
    workspace.conversation_projects["conv_checkout"] = project.id
    version_result = service.create_version(
        invocation(
            "version.create",
            conversation_id="conv_checkout",
            input_payload={"name": "2026.08"},
        )
    )
    version = workspace.versions[project.id][0]

    assert version_result.object_refs == [f"version:{version.id}"]
    assert workspace.projects[project.id].active_version == "2026.08"
    assert workspace.release_readiness[version.id].status == "Draft"

    imported = service.import_version_inputs(
        invocation(
            "version.inputs.import",
            input_payload={
                "project_id": project.id,
                "version_id": version.id,
                "us_items": [
                    {
                        "id": "US-101",
                        "title": "Confirm checkout",
                        "owner": "Unassigned",
                    }
                ],
            },
        )
    )
    assert imported.object_refs == [f"version:{version.id}", "us:US-101"]

    service.assign_version_participants(
        invocation(
            "version.participants.assign",
            input_payload={
                "project_id": project.id,
                "version_id": version.id,
                "assignments": [{"us_id": "US-101", "owner": "Alicia"}],
            },
        )
    )
    service.initialize_version_risk(
        invocation(
            "version.risk.initialize",
            input_payload={
                "project_id": project.id,
                "version_id": version.id,
            },
        )
    )

    us_item = workspace.us_items[project.id][0]
    assert us_item.owner == "Alicia"
    assert us_item.risk in {"low", "medium", "high"}
    assert workspace.projects[project.id].progress >= 30
    assert workspace.versions[project.id][0].status == "active"


def test_start_us_task_materializes_context_only_when_evidence_is_indexed() -> None:
    workspace = InMemoryProjectVersionWorkspace()
    system_image = StubSystemImageOperations()
    service = ProjectVersionApplicationService(
        workspace,
        system_image,
        EmptyContextQueries(),
    )
    project = service.create_project_record("Evidence Project")
    version = service.create_version_record(project.id, "2026.09")
    workspace.replace_us_items(project.id, version.id, [
        USItem(
            id="US-202",
            title="Audit payment",
            owner="QA",
            status="draft",
            risk="medium",
            progress=0,
            next_action="Start",
        )
    ])
    workspace.indexed_projects.add(project.id)

    result = asyncio.run(
        service.start_us_task(
            invocation(
                "us.task.start",
                input_payload={
                    "project_id": project.id,
                    "version_id": version.id,
                    "us_id": "US-202",
                },
            )
        )
    )

    assert system_image.materialized_projects == [project.id]
    assert workspace.us_items[project.id][0].status == "analysis"
    assert result.requires_followup is True
    assert "system_image.context.materialize" in result.next_tools


def test_version_us_items_are_isolated_across_project_versions() -> None:
    workspace = InMemoryProjectVersionWorkspace()
    service = ProjectVersionApplicationService(
        workspace,
        StubSystemImageOperations(),
        EmptyContextQueries(),
    )
    project = service.create_project_record("Versioned Checkout")
    first_version = service.create_version_record(project.id, "2026.08")
    service.import_version_inputs(
        invocation(
            "version.inputs.import",
            input_payload={
                "project_id": project.id,
                "version_id": first_version.id,
                "us_items": [{"id": "US-A", "title": "First release"}],
            },
        )
    )

    second_version = service.create_version_record(project.id, "2026.09")
    service.import_version_inputs(
        invocation(
            "version.inputs.import",
            input_payload={
                "project_id": project.id,
                "version_id": second_version.id,
                "us_items": [{"id": "US-B", "title": "Second release"}],
            },
        )
    )

    assert [item.id for item in workspace.list_us_items(project.id, first_version.id)] == ["US-A"]
    assert [item.id for item in workspace.list_us_items(project.id, second_version.id)] == ["US-B"]
    assert [item.id for item in workspace.us_items[project.id]] == ["US-B"]


def test_first_quality_version_adopts_unversioned_system_image_us_items() -> None:
    workspace = InMemoryProjectVersionWorkspace()
    project_versions = ProjectVersionApplicationService(
        workspace,
        StubSystemImageOperations(),
        EmptyContextQueries(),
    )
    project = project_versions.create_project_record("Legacy System Image")
    legacy_item = USItem(
        id="US-LEGACY",
        title="System-image-derived requirement",
        owner="QA",
        status="draft",
        risk="medium",
        progress=0,
        next_action="Start",
    )
    workspace.replace_us_items(project.id, None, [legacy_item])

    version = QualityLoopVersionContextApplicationService(
        workspace,
        project_versions,
    ).active_or_create_version(project.id)

    assert workspace.version_us_items[(project.id, None)] == []
    assert workspace.list_us_items(project.id, version.id) == [legacy_item]
    assert workspace.us_items[project.id] == [legacy_item]


def test_start_us_task_adopts_unversioned_system_image_us_items() -> None:
    workspace = InMemoryProjectVersionWorkspace()
    service = ProjectVersionApplicationService(
        workspace,
        StubSystemImageOperations(),
        EmptyContextQueries(),
    )
    project = service.create_project_record("System Image Task Start")
    legacy_item = USItem(
        id="US-SYSTEM-IMAGE",
        title="Requirement discovered before version creation",
        owner="QA",
        status="draft",
        risk="medium",
        progress=0,
        next_action="Start",
    )
    workspace.replace_us_items(project.id, None, [legacy_item])

    result = asyncio.run(
        service.start_us_task(
            invocation(
                "us.task.start",
                input_payload={
                    "project_id": project.id,
                    "us_id": legacy_item.id,
                },
            )
        )
    )

    version = workspace.versions[project.id][0]
    adopted = workspace.list_us_items(project.id, version.id)
    assert version.name == "Initial Quality Loop"
    assert [item.id for item in adopted] == [legacy_item.id]
    assert adopted[0].status == "analysis"
    assert result.object_refs[:3] == [
        f"project:{project.id}",
        f"version:{version.id}",
        f"us:{legacy_item.id}",
    ]
