from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from ...application.agent.agent_models import AgentMemoryItem, ConversationSession
from ...domain.platform.llm_call import LLMCallContext
from ...application.system_image.retrieval import (
    SystemImageMemoryHit,
    SystemImageMemorySearchResult,
    SystemImageRetriever,
)
from ...application.system_image.retrieval_port import (
    HybridRetrievalHit,
    HybridRetrievalQuery,
    SystemImageRetrievalIndexPort,
)
from ...application.system_image.system_image_models import RerankRecord, RetrievalRun
from ...application.system_image.ports import SystemImageWorkspacePort
from ..persistence.conversation_repository import ConversationRepository
from ..persistence.system_image_repository import (
    SystemImageProjectSnapshot,
    SystemImageRepository,
)


@dataclass(frozen=True)
class _EmbeddingProfile:
    baseline_id: str
    model_name: str
    model_version: str
    dimensions: int
    allow_fallback: bool


@dataclass(frozen=True)
class _Candidate:
    hit: SystemImageMemoryHit
    search_text: str
    embedding_record_id: str | None = None


class SQLAlchemySystemImageRetriever(SystemImageRetriever):
    """Durable Agent retrieval over PostgreSQL FTS, pgvector, and rerank routes."""

    def __init__(
        self,
        *,
        system_images: SystemImageRepository,
        conversations: ConversationRepository,
        retrieval_index: SystemImageRetrievalIndexPort,
        workspace: SystemImageWorkspacePort,
    ) -> None:
        self._system_images = system_images
        self._conversations = conversations
        self._retrieval_index = retrieval_index
        self._workspace = workspace

    async def search_project_memory(
        self,
        conversation: ConversationSession,
        query: str,
        *,
        limit: int = 8,
        trace: bool = False,
    ) -> SystemImageMemorySearchResult:
        project_id = conversation.project_id
        normalized_query = " ".join(query.split())
        if not project_id or not normalized_query:
            return SystemImageMemorySearchResult()

        terms = self._query_terms(normalized_query)
        snapshot = self._system_images.load_project_snapshot(project_id)
        memories = self._conversations.list_agent_memory_items(
            owner_ref=f"project:{project_id}",
            memory_scope="project_long_term",
            status="active",
            limit=24,
        )
        profile = self._embedding_profile(snapshot, conversation)
        candidates = self._durable_lexical_candidates(snapshot, memories, terms)
        indexed_hits: list[HybridRetrievalHit] = []
        query_embedding: Any | None = None

        if profile is not None:
            query_embedding = await self._workspace.embed_texts(
                [normalized_query],
                call_context=LLMCallContext(
                    purpose="agent.memory.embedding",
                    project_id=project_id,
                    version_id=conversation.version_id,
                    task_id=conversation.task_id or conversation.us_id,
                    conversation_id=conversation.id,
                ),
            )
            query_vector = (
                list(query_embedding.vectors[0])
                if getattr(query_embedding, "vectors", None)
                else []
            )
            if (
                query_vector
                and query_embedding.model_name == profile.model_name
                and len(query_vector) == profile.dimensions
            ):
                indexed_hits = self._retrieval_index.search(
                    HybridRetrievalQuery(
                        project_id=project_id,
                        baseline_id=profile.baseline_id,
                        query_text=normalized_query,
                        query_vector=tuple(query_vector),
                        embedding_model=profile.model_name,
                        embedding_version=profile.model_version,
                        dimensions=profile.dimensions,
                        limit=max(24, limit * 3),
                        candidate_limit=max(72, limit * 9),
                        allow_fallback_vectors=(
                            profile.allow_fallback or query_embedding.mode != "live"
                        ),
                    )
                )
                self._merge_index_candidates(candidates, indexed_hits)

        ordered_candidates = self._diverse_slice(
            sorted(
                candidates.values(),
                key=lambda item: (-item.hit.score, item.hit.kind, item.hit.ref),
            ),
            max(24, limit * 3),
        )
        rerank_result: Any | None = None
        ranked_candidates = ordered_candidates
        if ordered_candidates:
            rerank_result = await self._workspace.rerank_candidates(
                query=normalized_query,
                candidates=[item.search_text for item in ordered_candidates],
                call_context=LLMCallContext(
                    purpose="agent.memory.rerank",
                    project_id=project_id,
                    version_id=conversation.version_id,
                    task_id=conversation.task_id or conversation.us_id,
                    conversation_id=conversation.id,
                ),
            )
            ranked_candidates = self._apply_rerank(
                ordered_candidates,
                getattr(rerank_result, "ranked_indices", []),
            )

        selected = self._diverse_slice(
            self._with_rank_scores(ranked_candidates),
            max(1, limit),
        )
        retrieval_refs: tuple[str, ...] = ()
        if trace:
            retrieval_refs = self._persist_trace(
                conversation=conversation,
                query=normalized_query,
                profile=profile,
                candidates=ordered_candidates,
                selected=selected,
                indexed_hits=indexed_hits,
                query_embedding=query_embedding,
                rerank_result=rerank_result,
            )
        return SystemImageMemorySearchResult(
            hits=tuple(item.hit for item in selected),
            retrieval_run_refs=retrieval_refs,
        )

    def _persist_trace(
        self,
        *,
        conversation: ConversationSession,
        query: str,
        profile: _EmbeddingProfile | None,
        candidates: list[_Candidate],
        selected: list[_Candidate],
        indexed_hits: list[HybridRetrievalHit],
        query_embedding: Any | None,
        rerank_result: Any | None,
    ) -> tuple[str, ...]:
        project_id = conversation.project_id
        if not project_id:
            return ()
        created_at = datetime.now(timezone.utc).isoformat()
        retrieval_id = f"retrieval_agent_memory_{uuid4().hex[:12]}"
        rerank_id = f"rerank_agent_memory_{uuid4().hex[:12]}" if rerank_result else None
        embedding_live = query_embedding is not None and query_embedding.mode == "live"
        rerank_live = rerank_result is not None and rerank_result.mode == "live"
        fallback_used = profile is None or not indexed_hits or not embedding_live or not rerank_live
        retrieval = RetrievalRun(
            id=retrieval_id,
            project_id=project_id,
            baseline_id=(profile.baseline_id if profile else self._fallback_baseline_id(project_id)),
            version_id=conversation.version_id,
            us_id=conversation.us_id,
            query=query,
            strategy="rule_based_fusion" if fallback_used else "hybrid_graph_vector",
            candidate_count=len(candidates),
            result_refs=[item.hit.ref for item in selected],
            embedding_record_ids=list(
                dict.fromkeys(
                    hit.embedding_record_id
                    for hit in indexed_hits
                    if hit.embedding_record_id
                )
            )[:72],
            rerank_record_id=rerank_id,
            fallback_used=fallback_used,
            created_at=created_at,
        )
        rerank = None
        if rerank_result is not None and rerank_id is not None:
            rerank = RerankRecord(
                id=rerank_id,
                project_id=project_id,
                retrieval_run_id=retrieval_id,
                rerank_model=rerank_result.model_name,
                rerank_version="settings.current",
                input_count=len(candidates),
                output_count=len(selected),
                status="completed" if rerank_live else "fallback",
                latency_ms=max(0, int(rerank_result.latency_ms)),
                fallback_reason=None if rerank_live else str(rerank_result.reason),
                created_at=created_at,
            )
        self._system_images.append_retrieval_trace(project_id, retrieval, rerank)
        self._workspace.refresh_project_read_model(project_id)
        return (f"retrieval_run:{retrieval_id}",)

    def _fallback_baseline_id(self, project_id: str) -> str:
        snapshot = self._system_images.load_project_snapshot(project_id)
        baseline = self._select_baseline(snapshot, None)
        return baseline.id if baseline is not None else f"baseline_pending_{project_id}"

    @classmethod
    def _embedding_profile(
        cls,
        snapshot: SystemImageProjectSnapshot,
        conversation: ConversationSession,
    ) -> _EmbeddingProfile | None:
        baselines = cls._ordered_baselines(snapshot, conversation.version_id)
        for baseline in baselines:
            records = [
                item
                for item in snapshot.embedding_records
                if item.baseline_id == baseline.id
                and item.status in {"ready", "fallback"}
                and item.dimensions > 0
            ]
            profile = cls._dominant_embedding_profile(records)
            if profile is not None:
                return _EmbeddingProfile(
                    baseline_id=baseline.id,
                    model_name=profile[0],
                    model_version=profile[1],
                    dimensions=profile[2],
                    allow_fallback=profile[3],
                )
        return None

    @staticmethod
    def _dominant_embedding_profile(records: Iterable[Any]) -> tuple[str, str, int, bool] | None:
        groups: dict[tuple[str, str, int, bool], int] = {}
        for item in records:
            key = (
                item.embedding_model,
                item.embedding_version,
                item.dimensions,
                item.status != "ready",
            )
            groups[key] = groups.get(key, 0) + 1
        if not groups:
            return None
        return max(
            groups,
            key=lambda key: (
                not key[3],
                groups[key],
                key[0],
                key[1],
                key[2],
            ),
        )

    @classmethod
    def _ordered_baselines(
        cls,
        snapshot: SystemImageProjectSnapshot,
        version_id: str | None,
    ) -> list[Any]:
        return sorted(
            snapshot.baselines,
            key=lambda item: (
                0 if version_id and item.source_version_id == version_id else 1,
                0 if item.kind == "official" else 1,
                0 if item.status in {"ready", "promoted"} else 1,
                item.updated_at,
                item.id,
            ),
        )

    @classmethod
    def _select_baseline(
        cls,
        snapshot: SystemImageProjectSnapshot,
        version_id: str | None,
    ) -> Any | None:
        ordered = cls._ordered_baselines(snapshot, version_id)
        return ordered[0] if ordered else None

    @classmethod
    def _durable_lexical_candidates(
        cls,
        snapshot: SystemImageProjectSnapshot,
        memories: list[AgentMemoryItem],
        terms: set[str],
    ) -> dict[str, _Candidate]:
        candidates: dict[str, _Candidate] = {}

        def add(ref: str, kind: str, text: str, boost: float = 0.0) -> None:
            score = cls._score_text(text, terms) + boost
            if score <= boost:
                return
            candidate = _Candidate(
                hit=SystemImageMemoryHit(
                    ref=ref,
                    kind=kind,
                    score=round(score, 6),
                    summary=cls._summary(text),
                ),
                search_text=text,
            )
            existing = candidates.get(ref)
            if existing is None or candidate.hit.score > existing.hit.score:
                candidates[ref] = candidate

        for item in snapshot.knowledge_objects:
            add(
                f"context_object:{item.id}",
                "context_object",
                " ".join([item.id, item.name, item.type, item.branch, *item.relations, *item.evidence]),
                0.2,
            )
        for source in snapshot.raw_assets:
            add(
                f"raw_asset:{source.id}",
                "raw_asset",
                " ".join(
                    [
                        source.id,
                        source.source_type,
                        source.source_label or "",
                        source.source_uri,
                        *source.evidence_refs,
                    ]
                ),
                0.1,
            )
        for chunk in snapshot.raw_asset_chunks:
            add(
                f"raw_asset_chunk:{chunk.id}",
                "raw_asset_chunk",
                " ".join(
                    [
                        chunk.id,
                        chunk.source_type,
                        chunk.chunk_kind,
                        chunk.section_path,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                    ]
                ),
                0.3,
            )
        for relationship in snapshot.relationships:
            add(
                f"context_relationship:{relationship.id}",
                "relationship",
                " ".join(
                    [
                        relationship.id,
                        relationship.relationship_type,
                        relationship.from_object_id,
                        relationship.to_object_id,
                        *relationship.source_refs,
                    ]
                ),
                min(0.4, relationship.confidence * 0.4),
            )
        for metric in snapshot.metric_snapshots:
            add(
                f"quality_metric:{metric.id}",
                "metric",
                " ".join(
                    [
                        metric.id,
                        metric.metric_group,
                        json.dumps(metric.metrics, ensure_ascii=False),
                        *metric.evidence_refs,
                    ]
                ),
                0.25,
            )
        for memory in memories:
            add(
                f"agent_memory:{memory.id}",
                "agent_memory",
                " ".join(
                    [
                        memory.id,
                        memory.summary,
                        *memory.source_refs,
                        *memory.object_refs,
                        *memory.evidence_refs,
                    ]
                ),
                0.5,
            )
        return candidates

    @classmethod
    def _merge_index_candidates(
        cls,
        candidates: dict[str, _Candidate],
        indexed_hits: list[HybridRetrievalHit],
    ) -> None:
        for item in indexed_hits:
            kind = cls._kind_for_ref(item.subject_ref)
            candidate = _Candidate(
                hit=SystemImageMemoryHit(
                    ref=item.subject_ref,
                    kind=kind,
                    score=round(max(0.0, item.fused_score) + 1.0, 6),
                    summary=cls._summary(item.search_text),
                ),
                search_text=item.search_text,
                embedding_record_id=item.embedding_record_id,
            )
            existing = candidates.get(item.subject_ref)
            if existing is None or candidate.hit.score >= existing.hit.score:
                candidates[item.subject_ref] = candidate

    @staticmethod
    def _apply_rerank(
        candidates: list[_Candidate],
        ranked_indices: Iterable[int],
    ) -> list[_Candidate]:
        ordered: list[_Candidate] = []
        seen: set[int] = set()
        for index in ranked_indices:
            if not isinstance(index, int) or index in seen or not (0 <= index < len(candidates)):
                continue
            seen.add(index)
            ordered.append(candidates[index])
        ordered.extend(item for index, item in enumerate(candidates) if index not in seen)
        return ordered

    @staticmethod
    def _with_rank_scores(candidates: list[_Candidate]) -> list[_Candidate]:
        total = max(1, len(candidates))
        return [
            _Candidate(
                hit=SystemImageMemoryHit(
                    ref=item.hit.ref,
                    kind=item.hit.kind,
                    score=round(item.hit.score + (total - rank) / total, 6),
                    summary=item.hit.summary,
                ),
                search_text=item.search_text,
                embedding_record_id=item.embedding_record_id,
            )
            for rank, item in enumerate(candidates)
        ]

    @staticmethod
    def _diverse_slice(candidates: list[_Candidate], limit: int) -> list[_Candidate]:
        """Keep critical evidence types from being crowded out by one dense source."""

        if not candidates or limit <= 0:
            return []
        selected = list(candidates[:limit])
        required_kinds = ("context_object", "raw_asset_chunk", "agent_memory")
        available_required = {
            kind for kind in required_kinds if any(item.hit.kind == kind for item in candidates)
        }
        rank_by_ref = {item.hit.ref: rank for rank, item in enumerate(candidates)}
        for kind in required_kinds:
            if kind not in available_required or any(item.hit.kind == kind for item in selected):
                continue
            candidate = next(item for item in candidates if item.hit.kind == kind)
            replacement_index = next(
                (
                    index
                    for index in range(len(selected) - 1, -1, -1)
                    if selected[index].hit.kind not in available_required
                    or sum(
                        1
                        for current in selected
                        if current.hit.kind == selected[index].hit.kind
                    )
                    > 1
                ),
                None,
            )
            if replacement_index is None:
                continue
            selected[replacement_index] = candidate
        return sorted(selected, key=lambda item: rank_by_ref[item.hit.ref])

    @staticmethod
    def _query_terms(query: str) -> set[str]:
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
        return {
            value.lower()
            for value in re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}", query)
            if len(value.strip()) >= 2 and value.lower() not in stopwords
        }

    @staticmethod
    def _score_text(text: str, terms: set[str]) -> float:
        lowered = text.lower()
        score = 0.0
        for term in terms:
            count = lowered.count(term)
            if count:
                score += 1.0 + min(count - 1, 3) * 0.2
        return score

    @staticmethod
    def _summary(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()[:360]

    @staticmethod
    def _kind_for_ref(ref: str) -> str:
        prefix, _, _ = ref.partition(":")
        return {
            "context_object": "context_object",
            "raw_asset_chunk": "raw_asset_chunk",
            "raw_asset": "raw_asset",
        }.get(prefix, prefix or "system_image")


__all__ = ["SQLAlchemySystemImageRetriever"]
