from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..agent.agent_models import ConversationSession


@dataclass(frozen=True)
class SystemImageMemoryHit:
    ref: str
    kind: str
    score: float
    summary: str


@dataclass(frozen=True)
class SystemImageMemorySearchResult:
    hits: tuple[SystemImageMemoryHit, ...] = ()
    retrieval_run_refs: tuple[str, ...] = ()


class SystemImageRetriever(Protocol):
    """Port used by the Agent memory layer to retrieve system-image context."""

    async def search_project_memory(
        self,
        conversation: ConversationSession,
        query: str,
        *,
        limit: int = 8,
        trace: bool = False,
    ) -> SystemImageMemorySearchResult:
        ...


__all__ = [
    "SystemImageMemoryHit",
    "SystemImageMemorySearchResult",
    "SystemImageRetriever",
]
