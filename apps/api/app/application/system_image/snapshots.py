from __future__ import annotations

from .ports import SystemImageOperationsPort


class SystemImageSnapshotQueryApplicationService:
    """System-image snapshot read use cases."""

    def __init__(self, operations: SystemImageOperationsPort) -> None:
        self._operations = operations

    def get_system_image(self, project_id: str):
        return self._operations.get(project_id)


__all__ = ["SystemImageSnapshotQueryApplicationService"]
