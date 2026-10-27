from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..agent.agent_models import ConversationSession
from ...domain.system_image.source_access import SourceAccessScope
from .publication_read_models import ImageReadState


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
    image_read_state: ImageReadState | None = None
    strategy: str = "legacy_hybrid"


class SystemImageRetriever(Protocol):
    """Port used by the Agent memory layer to retrieve system-image context."""

    async def search_project_memory(
        self,
        conversation: ConversationSession,
        query: str,
        *,
        limit: int = 8,
        trace: bool = False,
        expected_scope: SourceAccessScope | None = None,
    ) -> SystemImageMemorySearchResult:
        ...


__all__ = [
    "SystemImageMemoryHit",
    "SystemImageMemorySearchResult",
    "SystemImageRetriever",
]
