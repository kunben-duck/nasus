from __future__ import annotations

from .state_hydration_ports import ProjectStateHydrationPort


class ProjectStateLoaderApplicationService:
    """Load persisted project-facing state into the compatibility store.

    Startup hydration spans three bounded contexts: project/version shell data,
    system-image context, and quality-loop assets. This loader keeps that
    cross-context cache hydration behind one explicit application port.
    """

    def __init__(self, hydration: ProjectStateHydrationPort) -> None:
        self._hydration = hydration

    def load(self) -> None:
        self._hydration.hydrate_all()


__all__ = ["ProjectStateLoaderApplicationService"]
