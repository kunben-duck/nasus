from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.system_image.retrieval_port import HybridRetrievalQuery
from apps.api.app.application.system_image.system_image_models import EmbeddingRecord
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.system_image.hybrid_retrieval import SQLAlchemySystemImageRetrievalIndex


def _record(
    *,
    record_id: str,
    project_id: str,
    baseline_id: str,
    chunk_ref: str,
    text: str,
    vector: list[float],
    model: str = "retrieval-test-model",
) -> EmbeddingRecord:
    return EmbeddingRecord(
        id=record_id,
        project_id=project_id,
        baseline_id=baseline_id,
        chunk_ref=chunk_ref,
        content_hash=f"sha256:{record_id}",
        embedding_model=model,
        embedding_version="v1",
        provider="mock",
        vector_ref=f"local-hash-vector://{record_id}",
        embedding_vector=vector,
        search_text=text,
        dimensions=len(vector),
        status="fallback",
        fallback_reason="test adapter",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_embedding_vectors_are_persisted_but_not_exposed_in_api_payload() -> None:
    init_database()
    project_id = f"project_retrieval_{uuid4().hex}"
    baseline_id = f"baseline_{uuid4().hex}"
    repository = SystemImageRepository()
    index = SQLAlchemySystemImageRetrievalIndex(repository)
    record = _record(
        record_id=f"embedding_{uuid4().hex}",
        project_id=project_id,
        baseline_id=baseline_id,
        chunk_ref="chunk_checkout",
        text="checkout payment recovery",
        vector=[1.0, 0.0, 0.0],
    )

    try:
        index.replace_embeddings(project_id, [record])
        loaded = repository.load_embedding_records()[project_id][0]
        assert loaded.embedding_vector == [1.0, 0.0, 0.0]
        assert loaded.search_text == "checkout payment recovery"
        assert "embedding_vector" not in loaded.model_dump()
        assert "search_text" not in loaded.model_dump()
    finally:
        index.replace_embeddings(project_id, [])

def test_hybrid_retrieval_ranks_semantic_and_lexical_match_first() -> None:
    init_database()
    project_id = f"project_retrieval_{uuid4().hex}"
    baseline_id = f"baseline_{uuid4().hex}"
    repository = SystemImageRepository()
    index = SQLAlchemySystemImageRetrievalIndex(repository)
    checkout = _record(
        record_id=f"embedding_{uuid4().hex}",
        project_id=project_id,
        baseline_id=baseline_id,
        chunk_ref="chunk_checkout",
        text="checkout payment retry and recovery",
        vector=[1.0, 0.0, 0.0],
    )
    profile = _record(
        record_id=f"embedding_{uuid4().hex}",
        project_id=project_id,
        baseline_id=baseline_id,
        chunk_ref="chunk_profile",
        text="customer profile avatar preferences",
        vector=[0.0, 1.0, 0.0],
    )

    try:
        index.replace_embeddings(project_id, [profile, checkout])
        hits = index.search(
            HybridRetrievalQuery(
                project_id=project_id,
                baseline_id=baseline_id,
                query_text="checkout payment failure",
                query_vector=(1.0, 0.0, 0.0),
                embedding_model="retrieval-test-model",
                embedding_version="v1",
                dimensions=3,
                allow_fallback_vectors=True,
            )
        )

        assert hits
        assert hits[0].subject_ref == "raw_asset_chunk:chunk_checkout"
        assert hits[0].vector_score > hits[-1].vector_score
        assert hits[0].lexical_score > 0
    finally:
        index.replace_embeddings(project_id, [])


def test_hybrid_retrieval_never_mixes_embedding_dimensions_or_models() -> None:
    init_database()
    project_id = f"project_retrieval_{uuid4().hex}"
    baseline_id = f"baseline_{uuid4().hex}"
    repository = SystemImageRepository()
    index = SQLAlchemySystemImageRetrievalIndex(repository)
    record = _record(
        record_id=f"embedding_{uuid4().hex}",
        project_id=project_id,
        baseline_id=baseline_id,
        chunk_ref="chunk_checkout",
        text="checkout payment recovery",
        vector=[1.0, 0.0, 0.0],
    )

    try:
        index.replace_embeddings(project_id, [record])
        wrong_dimension = index.search(
            HybridRetrievalQuery(
                project_id=project_id,
                baseline_id=baseline_id,
                query_text="checkout",
                query_vector=(1.0, 0.0),
                embedding_model="retrieval-test-model",
                embedding_version="v1",
                dimensions=2,
                allow_fallback_vectors=True,
            )
        )
        wrong_model = index.search(
            HybridRetrievalQuery(
                project_id=project_id,
                baseline_id=baseline_id,
                query_text="checkout",
                query_vector=(1.0, 0.0, 0.0),
                embedding_model="different-model",
                embedding_version="v1",
                dimensions=3,
                allow_fallback_vectors=True,
            )
        )
        assert wrong_dimension == []
        assert wrong_model == []
    finally:
        index.replace_embeddings(project_id, [])
