from __future__ import annotations

from .ports import SystemImageOperationsPort


class SystemImageLifecycleApplicationService:
    """System-image materialization and baseline lifecycle use cases."""

    def __init__(self, operations: SystemImageOperationsPort) -> None:
        self._operations = operations

    async def materialize_context(self, project_id: str):
        return await self._operations.materialize_context(project_id)

    async def initialize_baseline(self, project_id: str):
        return await self._operations.initialize_baseline(project_id)


__all__ = ["SystemImageLifecycleApplicationService"]
