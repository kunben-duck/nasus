from __future__ import annotations

from ...domain.system_image.chunking import stable_hash
from ...domain.platform.llm_call import LLMCallContext
from .ports import SystemImageWorkspacePort
from .raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from .system_image_models import EmbeddingRecord, KnowledgeObject, RawAssetChunk, RawAssetRecord


class SystemImageEmbeddingRecordApplicationService:
    """Materializes embedding records for system-image sources, chunks, and objects."""

    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        raw_asset_chunks: SystemImageRawAssetChunkApplicationService,
    ) -> None:
        self._workspace = workspace
        self._raw_asset_chunks = raw_asset_chunks

    async def materialize(
        self,
        project_id: str,
        *,
        baseline_id: str,
        sources: list[RawAssetRecord],
        chunks: list[RawAssetChunk],
        objects: list[KnowledgeObject],
        captured_at: str,
    ) -> list[EmbeddingRecord]:
        pending: list[tuple[str, str | None, str | None, str | None, str, str]] = []
        records: list[EmbeddingRecord] = []

        for chunk in chunks[:96]:
            content_hash = chunk.content_hash
            record_id = f"embedding_{project_id}_{chunk.id}"
            pending.append((
                record_id,
                None,
                None,
                chunk.id,
                content_hash,
                self._raw_asset_chunks.chunk_text(chunk),
            ))

        for source in [source for source in sources if source.ingestion_status == "indexed"][:24]:
            content_hash = source.content_hash or stable_hash([source.source_type, source.source_uri])
            record_id = f"embedding_{project_id}_{source.id}"
            pending.append((
                record_id,
                source.id,
                None,
                None,
                content_hash,
                "\n".join([
                    source.source_type,
                    source.source_label or "",
                    source.source_uri,
                    content_hash,
                    *source.evidence_refs[:12],
                ]),
            ))

        for item in objects[:48]:
            content_hash = stable_hash([item.id, item.name, item.type, *item.evidence])
            record_id = f"embedding_{project_id}_{item.id}"
            pending.append((
                record_id,
                None,
                item.id,
                None,
                content_hash,
                "\n".join([item.type, item.name, item.branch, *item.evidence[:12], *item.relations[:12]]),
            ))

        embedding_result = await self._workspace.embed_texts(
            [item[-1] for item in pending],
            call_context=LLMCallContext(
                purpose="system_image.embedding.materialize",
                project_id=project_id,
            ),
        )
        status = "ready" if embedding_result.mode == "live" else "fallback"
        fallback_reason = None if embedding_result.mode == "live" else embedding_result.reason

        chunk_embedding_ids: dict[str, str] = {}
        for index, (record_id, source_ref, object_ref, chunk_ref, content_hash, search_text) in enumerate(pending):
            vector = embedding_result.vectors[index] if index < len(embedding_result.vectors) else []
            record = EmbeddingRecord(
                id=record_id,
                project_id=project_id,
                baseline_id=baseline_id,
                source_ref=source_ref,
                object_ref=object_ref,
                chunk_ref=chunk_ref,
                content_hash=content_hash,
                embedding_model=embedding_result.model_name,
                provider=embedding_result.provider,
                vector_ref=self.vector_ref(project_id, record_id, content_hash, status),
                dimensions=len(vector) or embedding_result.dimensions,
                embedding_vector=vector,
                search_text=search_text,
                status=status,
                fallback_reason=fallback_reason,
                created_at=captured_at,
            )
            records.append(record)
            if chunk_ref:
                chunk_embedding_ids[chunk_ref] = record.id

        for chunk in chunks:
            if chunk.id in chunk_embedding_ids:
                chunk.embedding_record_id = chunk_embedding_ids[chunk.id]

        return records

    @staticmethod
    def vector_ref(project_id: str, record_id: str, content_hash: str, status: str) -> str:
        namespace = "pgvector" if status == "ready" else "local-hash-vector"
        return f"{namespace}://system-image/{project_id}/{record_id}/{content_hash.removeprefix('sha256:')[:16]}"


__all__ = ["SystemImageEmbeddingRecordApplicationService"]
