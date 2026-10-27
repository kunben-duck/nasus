from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ...domain.system_image.document_projection import DocumentObservation
from .source_ports import SourceTextUnit
from .system_image_models import RawAssetRecord


@dataclass(frozen=True)
class DocumentExtraction:
    observations: tuple[DocumentObservation, ...]
    files: tuple[dict, ...]


@dataclass(frozen=True)
class RegisteredDocument:
    entity_id: str
    document_revision_id: str
    source_revision_id: str
    title: str
    kind: str
    evidence_ids: tuple[str, ...]
    payload: dict


class DocumentExtractorPort(Protocol):
    def extract(self, source_type: str, units: Sequence[SourceTextUnit]) -> DocumentExtraction: ...


class DocumentProjectionPort(Protocol):
    def record(self, source: RawAssetRecord, result: DocumentExtraction,
               units: Sequence[SourceTextUnit], *, captured_at: str) -> tuple[RegisteredDocument, ...]: ...


class DocumentProjectionApplicationService:
    def __init__(self, extractor: DocumentExtractorPort, registry: DocumentProjectionPort):
        self.extractor, self.registry = extractor, registry

    def extract(self, source: RawAssetRecord, units: Sequence[SourceTextUnit], *, captured_at: str):
        if source.source_type not in {"us_doc", "test_asset"}:
            raise ValueError("document projection requires requirements or test source")
        result = self.extractor.extract(source.source_type, units)
        return self.registry.record(source, result, units, captured_at=captured_at)
