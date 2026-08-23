from __future__ import annotations

from typing import List

from ..agent.agent_models import ConversationSession
from .read_query_ports import TopLevelContentReadPort
from .read_models import BuildResponse, DashboardResponse, DocumentationEntry, WelcomeResponse


class TopLevelContentApplicationService:
    """Top-level studio read models for welcome, build, dashboard, and docs.

    These pages are platform-owned BFF reads. Response assembly remains in the
    application layer while projection access enters through an explicit port.
    """

    def __init__(self, read_model: TopLevelContentReadPort) -> None:
        self._read_model = read_model

    def get_welcome(self) -> WelcomeResponse:
        visible_ids = self._read_model.visible_project_ids()
        recent_conversations = [
            conversation
            for conversation in self._read_model.list_conversations()
            if self._conversation_visible(conversation, visible_ids)
        ][:3]
        recent_versions = [
            version
            for project_id in visible_ids
            for version in self._read_model.list_versions(project_id)
        ][:3]
        return WelcomeResponse(
            recent_projects=[
                project
                for project in self._read_model.list_projects()
                if project.id in visible_ids
            ][:3],
            recent_versions=recent_versions,
            recent_conversations=recent_conversations,
        )

    def get_build(self) -> BuildResponse:
        visible_ids = self._read_model.visible_project_ids()
        drafts = [
            project
            for project in self._read_model.list_projects()
            if project.id in visible_ids and project.status in {"draft", "active"}
        ]
        return BuildResponse(
            drafts=drafts,
            imports_health=["Git reachable", "US parser ready", "UX parser pending optional sources"],
            provider_health="healthy",
        )

    def get_dashboard(self) -> DashboardResponse:
        visible_ids = self._read_model.visible_project_ids()
        projects = [
            project
            for project in self._read_model.list_projects()
            if project.id in visible_ids
        ]
        return DashboardResponse(
            active_projects=len(projects),
            running_versions=sum(
                len(self._read_model.list_versions(project_id))
                for project_id in visible_ids
            ),
            blocked_items=sum(project.blocked_items for project in projects),
            pending_approvals=sum(project.pending_approvals for project in projects),
            failed_runs=sum(
                1
                for project_id in visible_ids
                for run in self._read_model.list_runs(project_id)
                if run.status == "failed"
            ),
            projects=projects,
        )

    def list_documentation(self) -> List[DocumentationEntry]:
        return list(self._read_model.list_documentation())

    def _conversation_visible(
        self,
        conversation: ConversationSession,
        visible_project_ids: set[str],
    ) -> bool:
        if conversation.project_id:
            return conversation.project_id in visible_project_ids
        return conversation.initiator_id == self._read_model.current_user_id()
