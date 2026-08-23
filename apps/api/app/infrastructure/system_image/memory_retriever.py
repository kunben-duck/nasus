from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ...application.agent.agent_models import ConversationSession
from ...application.system_image.retrieval import (
    SystemImageMemoryHit,
    SystemImageMemorySearchResult,
    SystemImageRetriever,
)
from ...application.system_image.system_image_models import RawAssetChunk
from .workspace_dependencies import SystemImageRetrievalState


class DefaultSystemImageRetriever(SystemImageRetriever):
    """Compatibility-backed lexical system-image retrieval adapter.

    The application layer depends only on ``SystemImageRetriever``. This
    adapter owns the transitional projection reads until every memory subject
    can be queried through the durable hybrid retrieval index.
    """

    def __init__(
        self,
        state: SystemImageRetrievalState,
        chunk_text_reader: Callable[[RawAssetChunk], str],
    ) -> None:
        self._state = state
        self._chunk_text_reader = chunk_text_reader

    async def search_project_memory(
        self,
        conversation: ConversationSession,
        query: str,
        *,
        limit: int = 8,
        trace: bool = False,
    ) -> SystemImageMemorySearchResult:
        del trace
        project_id = conversation.project_id
        if not project_id:
            return SystemImageMemorySearchResult()
        terms = self._query_terms(query)
        if not terms:
            return SystemImageMemorySearchResult()

        hits: dict[str, SystemImageMemoryHit] = {}

        def add_hit(ref: str, kind: str, text: str, base_score: float = 0.0) -> None:
            score = self._score_text(text, terms) + base_score
            if score <= 0:
                return
            summary = re.sub(r"\s+", " ", text).strip()[:360]
            existing = hits.get(ref)
            if existing is None or score > existing.score:
                hits[ref] = SystemImageMemoryHit(
                    ref=ref,
                    kind=kind,
                    score=round(score, 3),
                    summary=summary,
                )

        projection = self._state.system_image
        for item in projection.knowledge_objects.get(project_id, []):
            text = " ".join([item.id, item.name, item.type, item.branch, *item.relations, *item.evidence])
            add_hit(f"context_object:{item.id}", "context_object", text, 0.2)

        for relationship in projection.context_relationships.get(project_id, []):
            text = " ".join(
                [
                    relationship.id,
                    relationship.relationship_type,
                    relationship.from_object_id,
                    relationship.to_object_id,
                    *relationship.source_refs,
                ]
            )
            add_hit(f"context_relationship:{relationship.id}", "relationship", text, relationship.confidence)

        for metric in projection.quality_metric_snapshots.get(project_id, []):
            text = " ".join(
                [
                    metric.id,
                    metric.metric_group,
                    json.dumps(metric.metrics, ensure_ascii=False),
                    *metric.evidence_refs,
                ]
            )
            add_hit(f"quality_metric:{metric.id}", "metric", text, 0.35)

        chunks_by_id = {
            chunk.id: chunk
            for chunk in projection.raw_asset_chunks.get(project_id, [])
        }
        for chunk in chunks_by_id.values():
            chunk_text = self._safe_chunk_text(chunk)
            text = " ".join(
                [
                    chunk.id,
                    chunk.source_type,
                    chunk.chunk_kind,
                    chunk.section_path,
                    chunk_text,
                ]
            )
            add_hit(f"raw_asset_chunk:{chunk.id}", "raw_asset_chunk", text, 0.45)

        for embedding in projection.embedding_records.get(project_id, []):
            ref = self._embedding_subject_ref(embedding)
            if not ref:
                continue
            subject_text = self._embedding_subject_text(embedding, chunks_by_id)
            add_hit(ref, "embedding", subject_text, 0.15 if embedding.status == "ready" else 0.05)

        for retrieval in projection.retrieval_runs.get(project_id, []):
            text = " ".join([retrieval.id, retrieval.query, *retrieval.result_refs[:16]])
            add_hit(f"retrieval_run:{retrieval.id}", "retrieval_run", text, 0.25)

        owner_ref = f"project:{project_id}"
        for memory in self._state.agent_memory_items.values():
            if (
                memory.owner_ref != owner_ref
                or memory.memory_scope != "project_long_term"
                or memory.status != "active"
            ):
                continue
            text = " ".join(
                [
                    memory.id,
                    memory.summary,
                    *memory.source_refs,
                    *memory.object_refs,
                    *memory.evidence_refs,
                ]
            )
            add_hit(f"agent_memory:{memory.id}", "agent_memory", text, 0.55)

        selected = sorted(hits.values(), key=lambda hit: (-hit.score, hit.kind, hit.ref))[:limit]
        return SystemImageMemorySearchResult(hits=tuple(selected))

    @staticmethod
    def _query_terms(query: str) -> set[str]:
        terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}", query)
            if len(term.strip()) >= 2
        }
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "what",
            "does",
            "about",
            "system",
            "image",
            "系统",
            "画像",
        }
        return {term for term in terms if term not in stopwords}

    @staticmethod
    def _score_text(text: str, terms: set[str]) -> float:
        lowered = text.lower()
        score = 0.0
        for term in terms:
            count = lowered.count(term)
            if count:
                score += 1.0 + min(count - 1, 3) * 0.2
        return score

    def _safe_chunk_text(self, chunk: Any) -> str:
        try:
            return self._chunk_text_reader(chunk)
        except (OSError, RuntimeError, ValueError):
            return " ".join([chunk.source_type, chunk.chunk_kind, chunk.section_path, chunk.content_hash])

    @staticmethod
    def _embedding_subject_ref(embedding: Any) -> str | None:
        if embedding.chunk_ref:
            return f"raw_asset_chunk:{embedding.chunk_ref}"
        if embedding.object_ref:
            return f"context_object:{embedding.object_ref}"
        if embedding.source_ref:
            return f"raw_asset:{embedding.source_ref}"
        return None

    def _embedding_subject_text(self, embedding: Any, chunks_by_id: dict[str, Any]) -> str:
        if embedding.chunk_ref and embedding.chunk_ref in chunks_by_id:
            chunk = chunks_by_id[embedding.chunk_ref]
            return " ".join(
                [
                    chunk.source_type,
                    chunk.chunk_kind,
                    chunk.section_path,
                    self._safe_chunk_text(chunk),
                ]
            )
        if embedding.object_ref:
            item = next(
                (
                    obj
                    for objects in self._state.system_image.knowledge_objects.values()
                    for obj in objects
                    if obj.id == embedding.object_ref
                ),
                None,
            )
            if item is not None:
                return " ".join([item.id, item.name, item.type, *item.relations, *item.evidence])
        if embedding.source_ref:
            source = next(
                (
                    raw
                    for sources in self._state.system_image.raw_assets.values()
                    for raw in sources
                    if raw.id == embedding.source_ref
                ),
                None,
            )
            if source is not None:
                return " ".join([source.id, source.source_type, source.source_uri, *source.evidence_refs])
        return " ".join([embedding.id, embedding.content_hash, embedding.vector_ref])


__all__ = ["DefaultSystemImageRetriever"]
