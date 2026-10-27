from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, Sequence

from ..platform.project_models import ProjectCard
from ...domain.system_image.source_snapshots import SourceSnapshotArtifact
from ...domain.system_image.source_inventory import SourceInventoryArtifact
from ...domain.system_image.source_tracking import require_tracked_ref
from ...domain.system_image.code_analysis import CodeFileAnalysis, CodeStructureFact, CodeStructureSpan
from ...domain.system_image.code_identity import CodeSymbolKey
from ...domain.system_image.code_provider import CodeProviderCapabilities, CodeProviderObservation
from ...domain.system_image.code_native_observation import CodeNativeQueryObservation
from .system_image_models import RawAssetRecord
from .build_lineage import NativeCodeExecutionPin


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
    tracked_ref: str | None = None

    def __post_init__(self):
        require_tracked_ref(self.source_type, self.tracked_ref)


@dataclass(frozen=True)
class IngestedSource:
    content_hash: str
    content_ref: str
    evidence_refs: list[str]
    file_count: int
    byte_count: int
    snapshot: SourceSnapshotArtifact | None = None
    inventory: SourceInventoryArtifact | None = None


class SourceAcquisitionFailed(OSError):
    def __init__(self, inventory: SourceInventoryArtifact) -> None:
        super().__init__("source acquisition is incomplete; inspect the source inventory")
        self.inventory = inventory


class SourceAcquisitionDenied(SourceAcquisitionFailed, PermissionError):
    def __init__(self, inventory: SourceInventoryArtifact) -> None:
        super().__init__(inventory)
        self.args = ("source contains a symbolic link or unreadable path; inspect the source inventory",)


class CodeIntelligenceUnavailable(RuntimeError):
    """A replaceable code provider cannot return a trustworthy projection."""


@dataclass(frozen=True)
class SourceTextUnit:
    relative_path: str
    text: str
    byte_count: int
    content_hash: str
    # Optional materialized repository root for infrastructure adapters that
    # need repository-wide analysis. It is never persisted as a domain ID.
    source_root: str | None = None
    text_is_lossless: bool = True


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
    symbol_key: CodeSymbolKey | None = None
    identity_status: Literal["exact", "ambiguous", "unresolved"] = "unresolved"
    location_precision: Literal["exact", "approximate"] = "approximate"
    supporting_spans: tuple[CodeStructureSpan, ...] = ()


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
    file_analyses: tuple[CodeFileAnalysis, ...] = ()
    structural_facts: tuple[CodeStructureFact, ...] = ()
    provider_observations: tuple[CodeProviderObservation, ...] = ()
    native_query_observations: tuple[CodeNativeQueryObservation, ...] = field(default=(), compare=False, repr=False)
    execution_pin: NativeCodeExecutionPin | None = field(default=None, compare=False, repr=False)


def code_projection_payload(result: CodeIntelligenceResult) -> dict:
    # Worker-owned query envelopes contain transient IDs, not canonical facts.
    payload = asdict(replace(result, native_query_observations=(), execution_pin=None))
    payload.pop("native_query_observations")
    payload.pop("execution_pin")
    return payload


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


class ControlledCodeIntelligencePort(CodeIntelligencePort, Protocol):
    """Execution checks remain owned by the application, not the provider."""

    def analyze_controlled(self, units: Sequence[SourceTextUnit], *,
                           check_current: Callable[[], None]) -> CodeIntelligenceResult: ...


class DeclaredCodeIntelligencePort(ControlledCodeIntelligencePort, Protocol):
    """Declarations are local metadata, not a readiness probe or an index job."""

    def capabilities(self) -> CodeProviderCapabilities: ...


class SourceCodeIntelligencePort(Protocol):
    def analyze_source(self, source: RawAssetRecord, units: Sequence[SourceTextUnit], *,
                       invocation_id: str, check_current: Callable[[], None]) -> CodeIntelligenceResult: ...


def analyze_with_control(adapter: CodeIntelligencePort, units: Sequence[SourceTextUnit],
                         check_current: Callable[[], None]) -> CodeIntelligenceResult:
    check_current()
    controlled = getattr(adapter, "analyze_controlled", None)
    result = controlled(units, check_current=check_current) if callable(controlled) else adapter.analyze(units)
    check_current()
    return result


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
    "CodeIntelligenceUnavailable",
    "CodeEntityCandidate",
    "CodeEntityKind",
    "CodeIntelligencePort",
    "CodeIntelligenceResult",
    "ControlledCodeIntelligencePort",
    "DeclaredCodeIntelligencePort",
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
    "analyze_with_control",
]
