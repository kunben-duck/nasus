from __future__ import annotations

from .ports import SystemImageWorkspacePort
from .system_image_models import KnowledgeObject


class SystemImageKnowledgeQueryApplicationService:
    """System-image knowledge object read use cases."""

    def __init__(self, workspace: SystemImageWorkspacePort) -> None:
        self._workspace = workspace

    def list_knowledge_objects(self, project_id: str) -> list[KnowledgeObject]:
        self._workspace.refresh_project_read_model(project_id)
        return self._workspace.list_knowledge_objects(project_id)

    def get_knowledge_object(self, project_id: str, object_id: str) -> KnowledgeObject:
        self._workspace.refresh_project_read_model(project_id)
        return next(
            item
            for item in self._workspace.list_knowledge_objects(project_id)
            if item.id == object_id
        )


__all__ = ["SystemImageKnowledgeQueryApplicationService"]
