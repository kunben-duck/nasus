from __future__ import annotations

from ...domain.system_image.chunking import (
    chunk_id,
    chunk_kind,
    content_hash,
    estimate_tokens,
    split_chunk_text,
)
from .ports import SystemImageWorkspacePort
from .source_ports import SourceIngestionPort
from .system_image_models import RawAssetChunk


class SystemImageRawAssetChunkApplicationService:
    """Materializes indexed raw assets into chunk records and chunk payloads."""

    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        source_ingestion: SourceIngestionPort,
    ) -> None:
        self._workspace = workspace
        self._source_ingestion = source_ingestion

    def materialize(self, project_id: str, *, captured_at: str) -> list[RawAssetChunk]:
        chunks: list[RawAssetChunk] = []
        indexed_sources = [
            item
            for item in self._workspace.list_raw_assets(project_id)
            if item.ingestion_status == "indexed"
        ]
        for source in indexed_sources:
            units = self._source_ingestion.extract_text_units(source)
            for unit_index, unit in enumerate(units):
                for chunk_index, chunk_text in enumerate(split_chunk_text(unit.text)):
                    chunk_hash = content_hash(chunk_text)
                    chunk_id_value = chunk_id(project_id, source.id, unit.relative_path, chunk_index, chunk_hash)
                    content_ref = self._workspace.put_json(
                        f"system-image/{project_id}/raw-asset-chunks/{source.id}/{chunk_hash.removeprefix('sha256:')}.json",
                        {
                            "project_id": project_id,
                            "raw_asset_id": source.id,
                            "source_type": source.source_type,
                            "relative_path": unit.relative_path,
                            "unit_index": unit_index,
                            "chunk_index": chunk_index,
                            "content_hash": chunk_hash,
                            "content": chunk_text,
                            "created_at": captured_at,
                        },
                    )
                    chunks.append(
                        RawAssetChunk(
                            id=chunk_id_value,
                            project_id=project_id,
                            raw_asset_id=source.id,
                            source_type=source.source_type,
                            chunk_kind=chunk_kind(source.source_type),
                            section_path=unit.relative_path,
                            content_ref=content_ref,
                            content_hash=chunk_hash,
                            token_estimate=estimate_tokens(chunk_text),
                            metadata={
                                "unit_index": unit_index,
                                "chunk_index": chunk_index,
                                "source_content_hash": unit.content_hash,
                                "byte_count": unit.byte_count,
                            },
                            created_at=captured_at,
                        )
                    )
        self._workspace.replace_raw_asset_chunks(project_id, chunks)
        return chunks

    def chunk_text(self, chunk: RawAssetChunk) -> str:
        try:
            payload = self._workspace.get_json(chunk.content_ref)
        except (OSError, RuntimeError, ValueError):
            return "\n".join([
                chunk.source_type,
                chunk.chunk_kind,
                chunk.section_path,
                chunk.content_hash,
            ])
        content = payload.get("content")
        if isinstance(content, str) and content.strip():
            return content
        return "\n".join([
            chunk.source_type,
            chunk.chunk_kind,
            chunk.section_path,
            chunk.content_hash,
        ])


__all__ = ["SystemImageRawAssetChunkApplicationService"]
