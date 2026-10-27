"""Prepared-index operations return Nasus DTOs, never native database handles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

from ...domain.system_image.code_index import CodeImpactProjection, CodeIndexStatus
from ...domain.system_image.code_provider import CodeProjectionGap, CodeProviderCapabilities
from ...domain.system_image.code_provider_protocol import CodeProviderContractReceipt
from .source_ports import CodeEntityCandidate, CodeIntelligenceResult, CodeRelationshipCandidate, SourceTextUnit


@dataclass(frozen=True)
class CodeEntityPage:
    index_id: str
    snapshot_hash: str
    items: tuple[CodeEntityCandidate, ...]
    next_cursor: Optional[str]
    normalized_count: int
    enumeration: str
    gaps: tuple[CodeProjectionGap, ...]


@dataclass(frozen=True)
class CodeRelationPage:
    index_id: str
    snapshot_hash: str
    items: tuple[CodeRelationshipCandidate, ...]
    next_cursor: Optional[str]
    normalized_count: int
    enumeration: str
    gaps: tuple[CodeProjectionGap, ...]


class PreparedCodeIndexPort(Protocol):
    def __enter__(self) -> PreparedCodeIndexPort: ...
    def __exit__(self, exc_type, exception, traceback) -> None: ...
    def capabilities(self) -> CodeProviderCapabilities: ...
    def prepare_index(self) -> CodeIndexStatus: ...
    def protocol_receipt(self) -> Optional[CodeProviderContractReceipt]: ...
    def status(self) -> CodeIndexStatus: ...
    def entities(self, *, cursor: Optional[str] = None, limit: int = 50) -> CodeEntityPage: ...
    def relations(self, *, cursor: Optional[str] = None, limit: int = 50) -> CodeRelationPage: ...
    def locate(self, provider_node_id: str) -> CodeEntityCandidate: ...
    def impact(self, provider_node_ids: Sequence[str], *, direction: str = "upstream",
               max_hops: int = 2, max_entities: int = 500) -> CodeImpactProjection: ...
    def read_projection(self) -> CodeIntelligenceResult: ...
    def cancel(self) -> CodeIndexStatus: ...
    def close(self) -> None: ...


class PreparedCodeIndexFactoryPort(Protocol):
    def open_index(self, units: Sequence[SourceTextUnit], *,
                   check_current: Callable[[], None], namespace: Optional[str] = None,
                   provider_fingerprint: Optional[str] = None) -> PreparedCodeIndexPort: ...
    def projection_fingerprint(self, *, check_current: Optional[Callable[[], None]] = None) -> str: ...
