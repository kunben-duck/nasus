from __future__ import annotations

from .projection_ports import ToolInvocationProjectionStatePort
from .tool_models import ToolInvocation


class ToolInvocationProjectionApplicationService:
    """Persists ToolInvocation facts used by conversation read models."""

    def __init__(self, state: ToolInvocationProjectionStatePort) -> None:
        self._state = state

    def persist_and_project(self, invocation: ToolInvocation) -> None:
        self._state.persist_and_project(invocation)

    def upsert_in_conversation(self, invocation: ToolInvocation) -> None:
        """Compatibility delegate for callers using the former projection name."""

        self._state.persist_and_project(invocation)


__all__ = ["ToolInvocationProjectionApplicationService"]
