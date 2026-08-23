from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .system_image_models import EmbeddingRecord


@dataclass(frozen=True)
class HybridRetrievalQuery:
    project_id: str
    baseline_id: str
    query_text: str
    query_vector: tuple[float, ...]
    embedding_model: str
    embedding_version: str
    dimensions: int
    limit: int = 24
    candidate_limit: int = 72
    allow_fallback_vectors: bool = False


@dataclass(frozen=True)
class HybridRetrievalHit:
    embedding_record_id: str
    subject_ref: str
    search_text: str
    vector_score: float
    lexical_score: float
    fused_score: float


class SystemImageRetrievalIndexPort(Protocol):
    """Anti-corruption boundary for the system-image retrieval index."""

    def replace_embeddings(self, project_id: str, records: Sequence[EmbeddingRecord]) -> None:
        ...

    def search(self, query: HybridRetrievalQuery) -> list[HybridRetrievalHit]:
        ...


__all__ = [
    "HybridRetrievalHit",
    "HybridRetrievalQuery",
    "SystemImageRetrievalIndexPort",
]
