"""System-image application services and contract models.

This package uses lazy exports so the root compatibility `models.py` can
re-export system-image DTOs during the DDD migration without creating eager
import cycles through services that still consume compatibility models.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BaselineRecord",
    "ContextExtractionService",
    "ContextObjectOverlay",
    "ContextRelationship",
    "EmbeddingRecord",
    "ExtractedContext",
    "KnowledgeObject",
    "QualityMetricSnapshot",
    "QualityProfile",
    "RawAssetChunk",
    "RawAssetRecord",
    "RerankRecord",
    "RetrievalRun",
    "SystemImageEmbeddingRecordApplicationService",
    "SystemImageQualityContextApplicationService",
    "SystemImageRawAssetChunkApplicationService",
    "SystemImageApplicationService",
    "SystemImageBuildState",
    "SystemImageKnowledgeQueryApplicationService",
    "SystemImageLifecycleApplicationService",
    "SystemImageMemoryContextApplicationService",
    "SystemImageMemoryHit",
    "SystemImageMemorySearchResult",
    "SystemImageOperationsPort",
    "SystemImagePersistenceApplicationService",
    "SystemImageRetrievalTraceApplicationService",
    "SystemImageResponse",
    "SystemImageRetriever",
    "SystemImageService",
    "SystemImageSnapshotQueryApplicationService",
    "SystemImageSourceBindingApplicationService",
    "SystemImageSourceIngestionApplicationService",
    "SourceIngestionPort",
    "SourceUploadApplicationService",
    "SourceUploadFile",
    "SourceUploadResult",
    "SourceSpec",
    "SourceTextUnit",
    "SystemImageUSWorkItemApplicationService",
    "SystemImageWorkspacePort",
    "TaskContext",
]

_EXPORT_MODULES = {
    "BaselineRecord": ".system_image_models",
    "ContextExtractionService": ".context_extraction",
    "ContextObjectOverlay": ".system_image_models",
    "ContextRelationship": ".system_image_models",
    "EmbeddingRecord": ".system_image_models",
    "ExtractedContext": ".context_extraction",
    "KnowledgeObject": ".system_image_models",
    "QualityMetricSnapshot": ".system_image_models",
    "QualityProfile": ".system_image_models",
    "RawAssetChunk": ".system_image_models",
    "RawAssetRecord": ".system_image_models",
    "RerankRecord": ".system_image_models",
    "RetrievalRun": ".system_image_models",
    "SystemImageEmbeddingRecordApplicationService": ".embedding_records",
    "SystemImageQualityContextApplicationService": ".quality_contexts",
    "SystemImageRawAssetChunkApplicationService": ".raw_asset_chunks",
    "SystemImageApplicationService": ".use_cases",
    "SystemImageBuildState": ".system_image_models",
    "SystemImageKnowledgeQueryApplicationService": ".knowledge_queries",
    "SystemImageLifecycleApplicationService": ".lifecycle",
    "SystemImageMemoryContextApplicationService": ".memory_context",
    "SystemImageMemoryHit": ".retrieval",
    "SystemImageMemorySearchResult": ".retrieval",
    "SystemImageOperationsPort": ".ports",
    "SystemImagePersistenceApplicationService": ".persistence",
    "SystemImageRetrievalTraceApplicationService": ".retrieval_traces",
    "SystemImageResponse": ".system_image_models",
    "SystemImageRetriever": ".retrieval",
    "SystemImageService": ".service",
    "SystemImageSnapshotQueryApplicationService": ".snapshots",
    "SystemImageSourceBindingApplicationService": ".source_bindings",
    "SystemImageSourceIngestionApplicationService": ".source_ingestion",
    "SourceIngestionPort": ".source_ports",
    "SourceUploadApplicationService": ".source_uploads",
    "SourceUploadFile": ".source_uploads",
    "SourceUploadResult": ".source_uploads",
    "SourceSpec": ".source_ports",
    "SourceTextUnit": ".source_ports",
    "SystemImageUSWorkItemApplicationService": ".us_work_items",
    "SystemImageWorkspacePort": ".ports",
    "TaskContext": ".system_image_models",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
