from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.agent.agent_models import (
    AgentMemoryItem,
    ConversationSession,
)
from apps.api.app.application.system_image.system_image_models import (
    BaselineRecord,
    EmbeddingRecord,
    KnowledgeObject,
)
from apps.api.app.infrastructure.llm.gateway import (
    EmbeddingBatchResult,
    RerankBatchResult,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.system_image_repository import (
    SystemImageRepository,
)
from apps.api.app.infrastructure.system_image.hybrid_retrieval import (
    SQLAlchemySystemImageRetrievalIndex,
)
from apps.api.app.infrastructure.system_image.sqlalchemy_memory_retriever import (
    SQLAlchemySystemImageRetriever,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveRetrievalWorkspace:
    def __init__(self) -> None:
        self.refreshes: list[str] = []

    async def embed_texts(self, texts, *, call_context=None):
        del call_context
        assert list(texts)
        return EmbeddingBatchResult(
            vectors=[[1.0, 0.0, 0.0] for _ in texts],
            provider="openai_compatible",
            model_name="retrieval-test-model",
            mode="live",
            dimensions=3,
            reason="provider_success",
        )

    async def rerank_candidates(self, *, query, candidates, call_context=None):
        del call_context
        assert query
        ranked_indices = sorted(
            range(len(candidates)),
            key=lambda index: (
                "project memory" not in candidates[index].lower(),
                "checkout" not in candidates[index].lower(),
                index,
            ),
        )
        return RerankBatchResult(
            ranked_indices=ranked_indices,
            provider="openai_compatible",
            model_name="rerank-test-model",
            mode="live",
            reason="provider_success",
            latency_ms=7,
        )

    def refresh_project_read_model(self, project_id: str) -> None:
        self.refreshes.append(project_id)


def _seed_project(
    repository: SystemImageRepository,
    *,
    project_id: str,
    baseline_id: str,
    suffix: str,
) -> None:
    repository.replace_system_image(
        project_id,
        sources=[],
        chunks=[],
        baselines=[
            BaselineRecord(
                id=baseline_id,
                project_id=project_id,
                kind="official",
                status="ready",
                updated_at=_now(),
            )
        ],
        relationships=[],
        overlays=[],
        metric_snapshots=[],
        embedding_records=[
            EmbeddingRecord(
                id=f"embedding_{suffix}",
                project_id=project_id,
                baseline_id=baseline_id,
                object_ref=f"object_{suffix}",
                content_hash=f"sha256:{suffix}",
                embedding_model="retrieval-test-model",
                embedding_version="settings.current",
                provider="openai_compatible",
                vector_ref=f"pgvector://embedding_{suffix}",
                embedding_vector=[1.0, 0.0, 0.0],
                search_text=f"{suffix} checkout payment recovery",
                dimensions=3,
                status="ready",
                created_at=_now(),
            )
        ],
        retrieval_runs=[],
        rerank_records=[],
        task_contexts=[],
        quality_profiles=[],
        knowledge_objects=[
            KnowledgeObject(
                id=f"object_{suffix}",
                name=f"{suffix} checkout service",
                type="service",
                branch="official",
                confidence="high",
                freshness="current",
            )
        ],
    )


def test_durable_agent_retrieval_is_project_scoped_reranked_and_traced() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_agent_retrieval_{suffix}"
    other_project_id = f"project_agent_retrieval_other_{suffix}"
    baseline_id = f"baseline_agent_retrieval_{suffix}"
    other_baseline_id = f"baseline_agent_retrieval_other_{suffix}"
    system_images = SystemImageRepository()
    conversations = ConversationRepository()
    workspace = LiveRetrievalWorkspace()
    _seed_project(
        system_images,
        project_id=project_id,
        baseline_id=baseline_id,
        suffix=f"checkout_{suffix}",
    )
    _seed_project(
        system_images,
        project_id=other_project_id,
        baseline_id=other_baseline_id,
        suffix=f"foreign_{suffix}",
    )
    project_memory = AgentMemoryItem(
        id=f"memory_{suffix}",
        memory_scope="project_long_term",
        owner_ref=f"project:{project_id}",
        summary="Project memory says checkout recovery is release critical.",
        object_refs=[f"context_object:object_checkout_{suffix}"],
        status="active",
        created_at=_now(),
    )
    foreign_memory = AgentMemoryItem(
        id=f"memory_foreign_{suffix}",
        memory_scope="project_long_term",
        owner_ref=f"project:{other_project_id}",
        summary="Foreign project memory must never be returned.",
        status="active",
        created_at=_now(),
    )
    conversations.upsert_agent_memory_item(project_memory)
    conversations.upsert_agent_memory_item(foreign_memory)
    retriever = SQLAlchemySystemImageRetriever(
        system_images=system_images,
        conversations=conversations,
        retrieval_index=SQLAlchemySystemImageRetrievalIndex(system_images),
        workspace=workspace,  # type: ignore[arg-type]
    )
    conversation = ConversationSession(
        id=f"conversation_{suffix}",
        session_id=f"session_{suffix}",
        title="Checkout retrieval",
        space_type="project",
        space_id=project_id,
        project_id=project_id,
    )

    result = asyncio.run(
        retriever.search_project_memory(
            conversation,
            "What does the system image know about checkout recovery?",
            limit=4,
            trace=True,
        )
    )

    refs = [hit.ref for hit in result.hits]
    assert refs[0] == f"agent_memory:{project_memory.id}"
    assert f"context_object:object_checkout_{suffix}" in refs
    assert all("foreign" not in ref for ref in refs)
    assert len(result.retrieval_run_refs) == 1
    assert workspace.refreshes == [project_id]

    snapshot = system_images.load_project_snapshot(project_id)
    assert len(snapshot.retrieval_runs) == 1
    assert len(snapshot.rerank_records) == 1
    retrieval = snapshot.retrieval_runs[0]
    rerank = snapshot.rerank_records[0]
    assert retrieval.strategy == "hybrid_graph_vector"
    assert retrieval.fallback_used is False
    assert retrieval.result_refs == refs
    assert retrieval.rerank_record_id == rerank.id
    assert rerank.retrieval_run_id == retrieval.id
    assert rerank.status == "completed"
    assert system_images.load_project_snapshot(other_project_id).retrieval_runs == []


def test_semantic_retrieval_still_runs_when_query_terms_are_stopwords() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_semantic_{suffix}"
    baseline_id = f"baseline_semantic_{suffix}"
    system_images = SystemImageRepository()
    _seed_project(
        system_images,
        project_id=project_id,
        baseline_id=baseline_id,
        suffix=f"checkout_{suffix}",
    )
    retriever = SQLAlchemySystemImageRetriever(
        system_images=system_images,
        conversations=ConversationRepository(),
        retrieval_index=SQLAlchemySystemImageRetrievalIndex(system_images),
        workspace=LiveRetrievalWorkspace(),  # type: ignore[arg-type]
    )
    conversation = ConversationSession(
        id=f"conversation_semantic_{suffix}",
        session_id=f"session_semantic_{suffix}",
        title="Semantic retrieval",
        space_type="project",
        space_id=project_id,
        project_id=project_id,
    )

    result = asyncio.run(
        retriever.search_project_memory(conversation, "system image", limit=2)
    )

    assert result.hits
    assert result.hits[0].ref == f"context_object:object_checkout_{suffix}"
