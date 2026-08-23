from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from ..platform.project_models import ProjectCard
from .system_image_models import RawAssetRecord


SourceType = Literal["code", "us_doc", "test_asset"]
CodeEntityKind = Literal[
    "module",
    "class",
    "interface",
    "enum",
    "function",
    "method",
    "api_route",
    "dependency",
]
CodeRelationshipKind = Literal["belongs_to", "depends_on", "calls", "exposes"]


@dataclass(frozen=True)
class SourceSpec:
    source_type: SourceType
    source_uri: str
    label: str | None = None
    credential_ref: str | None = None


@dataclass(frozen=True)
class IngestedSource:
    content_hash: str
    content_ref: str
    evidence_refs: list[str]
    file_count: int
    byte_count: int


@dataclass(frozen=True)
class SourceTextUnit:
    relative_path: str
    text: str
    byte_count: int
    content_hash: str
    # Optional materialized repository root for infrastructure adapters that
    # need repository-wide analysis. It is never persisted as a domain ID.
    source_root: str | None = None


@dataclass(frozen=True)
class CodeEntityCandidate:
    """Provider-neutral code entity emitted by a code-intelligence adapter."""

    provider_node_id: str
    name: str
    qualified_name: str
    entity_kind: CodeEntityKind
    relative_path: str
    language: str
    start_line: int
    end_line: int
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class CodeRelationshipCandidate:
    """Provider-neutral relationship; provider IDs remain adapter metadata only."""

    from_provider_node_id: str
    relationship_kind: CodeRelationshipKind
    to_provider_node_id: str
    confidence: float
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class CodeIntelligenceResult:
    provider: str
    provider_version: str
    entities: tuple[CodeEntityCandidate, ...]
    relationships: tuple[CodeRelationshipCandidate, ...]
    evidence_refs: tuple[str, ...]
    unsupported_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaterializedSource:
    local_path: Path
    connector_kind: str
    source_ref: str
    revision: str
    evidence_refs: tuple[str, ...]


class SourceConnector(Protocol):
    connector_kind: str

    def supports(self, source: RawAssetRecord) -> bool: ...

    def materialize(self, source: RawAssetRecord, *, refresh: bool) -> MaterializedSource: ...


class SourceCredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> str: ...


class SourceIngestionPort(Protocol):
    def normalize_specs(self, raw_specs: Any) -> list[SourceSpec]: ...

    def ingest(self, source: RawAssetRecord) -> IngestedSource: ...

    def extract_text_units(self, source: RawAssetRecord) -> list[SourceTextUnit]: ...


class CodeIntelligencePort(Protocol):
    """Application port isolating Tree-sitter/MCP/code-graph provider details."""

    def analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult: ...


class SystemImageIngestionProjectionPort(Protocol):
    """Write-side projection boundary used by source ingestion use cases."""

    def mutation_guard(
        self,
        project_id: str,
    ) -> AbstractContextManager[None]: ...

    def get_project(self, project_id: str) -> ProjectCard: ...

    def list_sources(self, project_id: str) -> list[RawAssetRecord]: ...

    def replace_sources(self, project_id: str, sources: list[RawAssetRecord]) -> None: ...

    def save_project(self, project: ProjectCard) -> None: ...

    def clear_derived_context(self, project_id: str) -> None: ...

    def clear_chunks(self, project_id: str) -> None: ...

    def persist(self, project_id: str) -> None: ...

    def refresh(self, project_id: str) -> None: ...


__all__ = [
    "CodeEntityCandidate",
    "CodeEntityKind",
    "CodeIntelligencePort",
    "CodeIntelligenceResult",
    "CodeRelationshipCandidate",
    "CodeRelationshipKind",
    "IngestedSource",
    "MaterializedSource",
    "SourceConnector",
    "SourceCredentialResolver",
    "SourceIngestionPort",
    "SourceSpec",
    "SourceTextUnit",
    "SourceType",
    "SystemImageIngestionProjectionPort",
]
