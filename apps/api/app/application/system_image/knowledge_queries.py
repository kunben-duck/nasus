from __future__ import annotations

from .snapshots import SystemImageSnapshotQueryApplicationService
from .system_image_models import KnowledgeObject


class SystemImageKnowledgeQueryApplicationService:
    """System-image knowledge object read use cases."""

    def __init__(self, snapshots: SystemImageSnapshotQueryApplicationService) -> None:
        self._snapshots = snapshots

    def list_knowledge_objects(self, project_id: str) -> list[KnowledgeObject]:
        return self._snapshots.get_system_image(project_id).objects

    def get_knowledge_object(self, project_id: str, object_id: str) -> KnowledgeObject:
        return next(
            item
            for item in self.list_knowledge_objects(project_id)
            if item.id == object_id
        )


__all__ = ["SystemImageKnowledgeQueryApplicationService"]
