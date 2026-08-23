from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Iterable, Sequence

from sqlalchemy import func, select

from ...application.system_image.retrieval_port import (
    HybridRetrievalHit,
    HybridRetrievalQuery,
    SystemImageRetrievalIndexPort,
)
from ...application.system_image.system_image_models import EmbeddingRecord
from ..persistence.db_models import EmbeddingRecord as EmbeddingRow
from ..persistence.system_image_repository import SystemImageRepository
from ..persistence.unit_of_work import session_scope


class SQLAlchemySystemImageRetrievalIndex(SystemImageRetrievalIndexPort):
    """PostgreSQL pgvector + FTS index with a deterministic SQLite test adapter."""

    def __init__(self, repository: SystemImageRepository) -> None:
        self._repository = repository

    def replace_embeddings(self, project_id: str, records: Sequence[EmbeddingRecord]) -> None:
        self._repository.replace_embedding_records(project_id, list(records))

    def search(self, query: HybridRetrievalQuery) -> list[HybridRetrievalHit]:
        if query.dimensions <= 0:
            return []
        with session_scope() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                vector_rows, lexical_rows = self._postgres_candidates(session, query)
            else:
                vector_rows, lexical_rows = self._local_candidates(session, query)
        return self._fuse(vector_rows, lexical_rows, query.limit)

    @staticmethod
    def _filters(query: HybridRetrievalQuery):
        statuses = ["ready"]
        if query.allow_fallback_vectors:
            statuses.append("fallback")
        return (
            EmbeddingRow.project_id == query.project_id,
            EmbeddingRow.baseline_id == query.baseline_id,
            EmbeddingRow.embedding_model == query.embedding_model,
            EmbeddingRow.embedding_version == query.embedding_version,
            EmbeddingRow.dimensions == query.dimensions,
            EmbeddingRow.status.in_(statuses),
        )

    def _postgres_candidates(self, session, query: HybridRetrievalQuery):
        filters = self._filters(query)
        vector_rows: list[tuple[EmbeddingRow, float]] = []
        if query.query_vector:
            distance = EmbeddingRow.embedding_vector.cosine_distance(list(query.query_vector))
            statement = (
                select(EmbeddingRow, distance.label("distance"))
                .where(*filters, EmbeddingRow.embedding_vector.is_not(None))
                .order_by(distance.asc())
                .limit(query.candidate_limit)
            )
            vector_rows = [
                (row, max(0.0, 1.0 - float(distance_value)))
                for row, distance_value in session.execute(statement).all()
                if distance_value is not None
            ]

        terms = sorted(self._query_terms(query.query_text))
        lexical_query = func.websearch_to_tsquery("simple", " OR ".join(terms) or query.query_text)
        lexical_rank = func.ts_rank_cd(
            func.to_tsvector("simple", EmbeddingRow.search_text),
            lexical_query,
        )
        lexical_statement = (
            select(EmbeddingRow, lexical_rank.label("lexical_rank"))
            .where(*filters, lexical_rank > 0)
            .order_by(lexical_rank.desc())
            .limit(query.candidate_limit)
        )
        lexical_rows = [
            (row, float(rank_value))
            for row, rank_value in session.execute(lexical_statement).all()
            if rank_value is not None
        ]
        return vector_rows, lexical_rows

    def _local_candidates(self, session, query: HybridRetrievalQuery):
        rows = session.scalars(select(EmbeddingRow).where(*self._filters(query))).all()
        vector_rows: list[tuple[EmbeddingRow, float]] = []
        lexical_rows: list[tuple[EmbeddingRow, float]] = []
        terms = self._query_terms(query.query_text)
        for row in rows:
            vector = self._vector_list(row.embedding_vector)
            if query.query_vector and len(vector) == query.dimensions:
                vector_rows.append((row, self._cosine_similarity(query.query_vector, vector)))
            lexical_score = self._lexical_score(row.search_text or "", terms)
            if lexical_score > 0:
                lexical_rows.append((row, lexical_score))
        vector_rows.sort(key=lambda item: item[1], reverse=True)
        lexical_rows.sort(key=lambda item: item[1], reverse=True)
        return vector_rows[: query.candidate_limit], lexical_rows[: query.candidate_limit]

    @classmethod
    def _fuse(
        cls,
        vector_rows: Iterable[tuple[EmbeddingRow, float]],
        lexical_rows: Iterable[tuple[EmbeddingRow, float]],
        limit: int,
    ) -> list[HybridRetrievalHit]:
        records: dict[str, EmbeddingRow] = {}
        vector_scores: dict[str, float] = {}
        lexical_scores: dict[str, float] = {}
        fused: defaultdict[str, float] = defaultdict(float)
        rank_constant = 60.0

        for rank, (row, score) in enumerate(vector_rows, start=1):
            records[row.id] = row
            vector_scores[row.id] = round(max(0.0, score), 6)
            fused[row.id] += 0.7 / (rank_constant + rank)
        for rank, (row, score) in enumerate(lexical_rows, start=1):
            records[row.id] = row
            lexical_scores[row.id] = round(max(0.0, score), 6)
            fused[row.id] += 0.3 / (rank_constant + rank)

        normalizer = 1.0 / (rank_constant + 1.0)
        ranked_ids = sorted(fused, key=lambda record_id: (-fused[record_id], record_id))[: max(1, limit)]
        return [
            HybridRetrievalHit(
                embedding_record_id=record_id,
                subject_ref=cls._subject_ref(records[record_id]),
                search_text=records[record_id].search_text or "",
                vector_score=vector_scores.get(record_id, 0.0),
                lexical_score=lexical_scores.get(record_id, 0.0),
                fused_score=round(fused[record_id] / normalizer, 6),
            )
            for record_id in ranked_ids
            if cls._subject_ref(records[record_id])
        ]

    @staticmethod
    def _subject_ref(row: EmbeddingRow) -> str:
        if row.chunk_ref:
            return f"raw_asset_chunk:{row.chunk_ref}"
        if row.object_ref:
            return f"context_object:{row.object_ref}"
        if row.source_ref:
            return f"raw_asset:{row.source_ref}"
        return ""

    @staticmethod
    def _query_terms(text: str) -> set[str]:
        return {
            value.lower()
            for value in re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}", text)
            if len(value.strip()) >= 2
        }

    @staticmethod
    def _lexical_score(text: str, terms: set[str]) -> float:
        if not terms:
            return 0.0
        lowered = text.lower()
        matched = sum(1 for term in terms if term in lowered)
        return matched / len(terms)

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return max(0.0, dot / (left_norm * right_norm))

    @staticmethod
    def _vector_list(value) -> list[float]:
        if value is None:
            return []
        return [float(item) for item in value]


__all__ = ["SQLAlchemySystemImageRetrievalIndex"]
