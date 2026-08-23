from __future__ import annotations

from typing import Protocol


class ProjectStateHydrationPort(Protocol):
    """Hydrate project, system-image, and quality-loop read projections."""

    def hydrate_all(self) -> None: ...


__all__ = ["ProjectStateHydrationPort"]
