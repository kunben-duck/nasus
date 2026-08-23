from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.agent.agent_models import (
    AgentMemoryItem,
    ConversationSession,
)
from apps.api.app.application.platform.project_models import ProjectCard
from apps.api.app.infrastructure.platform.query_read_model import (
    SQLAlchemyAgentQueryReadModel,
)


def _project(project_id: str) -> ProjectCard:
    return ProjectCard(
        id=project_id,
        name=project_id,
        code=project_id.upper(),
        summary="Persisted project",
        status="active",
        risk="low",
        progress=10,
        active_version="Not started",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="not_started",
    )


@dataclass
class ProjectsStub:
    items: list[ProjectCard]

    def list_projects(self):
        return list(self.items)

    def get_project(self, project_id: str):
        return next((item for item in self.items if item.id == project_id), None)

    def list_versions(self, _project_id: str):
        return []


class QualityLoopStub:
    def list_us_items(self, _project_id: str):
        return []

    def list_asset_lanes(self, _project_id: str):
        return {}

    def list_runs(self, _project_id: str):
        return []

    def list_approvals(self, _project_id: str):
        return []


@dataclass
class ConversationsStub:
    items: dict[str, ConversationSession] = field(default_factory=dict)
    memory_items: list[AgentMemoryItem] = field(default_factory=list)

    def get_conversation(self, conversation_id: str):
        return self.items.get(conversation_id)

    def load_agent_memory_items(self):
        return list(self.memory_items)


def _conversation(conversation_id: str, project_id: str) -> ConversationSession:
    return ConversationSession(
        id=conversation_id,
        session_id=f"session-{conversation_id}",
        title=conversation_id,
        space_type="project",
        space_id=project_id,
        project_id=project_id,
        initiator_id="user-1",
        status="active",
    )


def _memory(project_id: str) -> AgentMemoryItem:
    return AgentMemoryItem(
        id=f"memory-{project_id}",
        memory_scope="project_long_term",
        owner_ref=f"project:{project_id}",
        summary="Project fact",
        status="active",
        created_at="2026-08-08T00:00:00+00:00",
    )


def test_agent_query_read_model_filters_projects_conversations_and_memory() -> None:
    conversations = ConversationsStub(
        items={
            "visible": _conversation("visible", "project-visible"),
            "hidden": _conversation("hidden", "project-hidden"),
        },
        memory_items=[_memory("project-visible"), _memory("project-hidden")],
    )
    read_model = SQLAlchemyAgentQueryReadModel(
        projects=ProjectsStub([_project("project-visible"), _project("project-hidden")]),  # type: ignore[arg-type]
        quality_loop=QualityLoopStub(),  # type: ignore[arg-type]
        conversations=conversations,  # type: ignore[arg-type]
        visible_project_ids=lambda: {"project-visible"},
        current_user_id=lambda: "user-1",
        project_id_for_us=lambda _us_id: None,
        get_system_image=lambda project_id: {"project_id": project_id},
    )

    assert [project.id for project in read_model.list_projects()] == [
        "project-visible"
    ]
    assert read_model.get_conversation("visible") is not None
    assert read_model.get_conversation("hidden") is None
    assert [item.owner_ref for item in read_model.list_agent_memory_items()] == [
        "project:project-visible"
    ]


def test_agent_query_read_model_rejects_hidden_project_reads() -> None:
    read_model = SQLAlchemyAgentQueryReadModel(
        projects=ProjectsStub([_project("project-hidden")]),  # type: ignore[arg-type]
        quality_loop=QualityLoopStub(),  # type: ignore[arg-type]
        conversations=ConversationsStub(),  # type: ignore[arg-type]
        visible_project_ids=set,
        current_user_id=lambda: "user-1",
        project_id_for_us=lambda _us_id: "project-hidden",
        get_system_image=lambda project_id: {"project_id": project_id},
    )

    try:
        read_model.get_project("project-hidden")
    except KeyError:
        pass
    else:
        raise AssertionError("hidden project read was not rejected")

    assert read_model.list_asset_lanes("us-hidden") == ()
