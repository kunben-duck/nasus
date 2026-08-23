from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.documentation_catalog import product_documentation_entries
from apps.api.app.application.platform.project_models import ProjectCard, VersionSummary
from apps.api.app.application.platform.top_level_content import TopLevelContentApplicationService
from apps.api.app.application.quality_loop.quality_models import RunSummary
from apps.api.app.infrastructure.platform.top_level_content import (
    SQLAlchemyTopLevelContentReadModel,
)


@dataclass
class ProjectRepositoryStub:
    projects: list[ProjectCard] = field(default_factory=list)
    versions: dict[str, list[VersionSummary]] = field(default_factory=dict)

    def list_projects(self) -> list[ProjectCard]:
        return list(self.projects)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return list(self.versions.get(project_id, ()))


@dataclass
class QualityLoopRepositoryStub:
    runs: dict[str, list[RunSummary]] = field(default_factory=dict)

    def list_runs(self, project_id: str) -> list[RunSummary]:
        return list(self.runs.get(project_id, ()))


@dataclass
class ConversationRepositoryStub:
    conversations: list[ConversationSession] = field(default_factory=list)

    def load_all(self) -> list[ConversationSession]:
        return list(self.conversations)


def _project(project_id: str, *, blocked: int = 0) -> ProjectCard:
    return ProjectCard(
        id=project_id,
        name=project_id,
        code=project_id.upper(),
        summary="Persisted project",
        status="active",
        risk="low",
        progress=25,
        active_version="Not started",
        blocked_items=blocked,
        pending_approvals=0,
        system_image_status="not_started",
    )


def test_top_level_content_reads_repository_state_on_every_request() -> None:
    projects = ProjectRepositoryStub(projects=[_project("project-a")])
    quality_loop = QualityLoopRepositoryStub()
    conversations = ConversationRepositoryStub()
    visible = {"project-a", "project-b"}
    read_model = SQLAlchemyTopLevelContentReadModel(
        projects=projects,  # type: ignore[arg-type]
        quality_loop=quality_loop,  # type: ignore[arg-type]
        conversations=conversations,  # type: ignore[arg-type]
        visible_project_ids=lambda: visible,
        current_user_id=lambda: "user-1",
        documentation=product_documentation_entries(),
    )
    service = TopLevelContentApplicationService(read_model)

    assert [item.id for item in service.get_dashboard().projects] == ["project-a"]

    projects.projects.append(_project("project-b", blocked=2))

    refreshed = service.get_dashboard()
    assert [item.id for item in refreshed.projects] == ["project-a", "project-b"]
    assert refreshed.blocked_items == 2


def test_product_documentation_is_available_without_demo_seed() -> None:
    read_model = SQLAlchemyTopLevelContentReadModel(
        projects=ProjectRepositoryStub(),  # type: ignore[arg-type]
        quality_loop=QualityLoopRepositoryStub(),  # type: ignore[arg-type]
        conversations=ConversationRepositoryStub(),  # type: ignore[arg-type]
        visible_project_ids=set,
        current_user_id=lambda: "user-1",
        documentation=product_documentation_entries(),
    )

    entries = TopLevelContentApplicationService(read_model).list_documentation()

    assert [entry.id for entry in entries] == [
        "DOC-START",
        "DOC-BRANCHING",
        "DOC-ASSET",
    ]
