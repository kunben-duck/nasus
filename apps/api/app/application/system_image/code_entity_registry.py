from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Protocol, Sequence

from ...domain.system_image.code_identity import CodeSymbolKey
from ...domain.system_image.code_alias import legacy_code_object_id  # Compatibility export for pinned V1 references.
from ...domain.system_image.evidence import DECODER_VERSION, source_lines, text_digest
from .source_ports import CodeIntelligenceResult, SourceTextUnit
from .system_image_models import RawAssetRecord


@dataclass(frozen=True)
class CodeEntityObservation:
    provider_node_id: str
    legacy_object_id: str
    symbol_key: CodeSymbolKey
    payload: dict


@dataclass(frozen=True)
class RegisteredCodeEntity:
    entity_id: str
    entity_revision_id: str
    source_revision_id: str


class CodeEntityRegistryPort(Protocol):
    def register(
        self, source: RawAssetRecord, observations: Sequence[CodeEntityObservation], *,
        provider: str, provider_version: str, captured_at: str,
    ) -> dict[str, RegisteredCodeEntity]: ...


class CodeEntityRegistrationService:
    def __init__(self, repository: CodeEntityRegistryPort) -> None:
        self.repository = repository

    def register(
        self, source: RawAssetRecord, result: CodeIntelligenceResult,
        units: Sequence[SourceTextUnit], *, captured_at: str,
    ) -> dict[str, RegisteredCodeEntity]:
        by_path = {unit.relative_path: unit for unit in units}
        if len(by_path) != len(units):
            raise ValueError("duplicate source text unit")
        if len({entity.provider_node_id for entity in result.entities}) != len(result.entities):
            raise ValueError("duplicate provider node ID")
        key_counts = Counter(item.symbol_key for item in result.entities if item.symbol_key is not None)
        failed_paths = {item.relative_path for item in result.file_analyses if item.status == "failed"}
        observations: list[CodeEntityObservation] = []
        for entity in result.entities:
            if entity.relative_path in failed_paths:
                continue
            key = entity.symbol_key
            if key is None or entity.identity_status != "exact" or key_counts[key] != 1:
                continue
            if (key.relative_path, key.language, key.kind, key.name) != (
                entity.relative_path, entity.language, entity.entity_kind, entity.name,
            ):
                raise ValueError("canonical symbol key does not match observation")
            unit = by_path.get(entity.relative_path)
            if unit is None:
                raise ValueError("code entity is outside the source snapshot")
            if not unit.text_is_lossless:
                raise ValueError("code entity source text is not lossless")
            lines = source_lines(unit.text)
            if not 1 <= entity.start_line <= entity.end_line <= len(lines):
                raise ValueError("code entity location is outside source text")
            approximate = entity.location_precision != "exact"
            snippet_hash = None if approximate else text_digest("".join(lines[entity.start_line - 1:entity.end_line]))
            supporting = []
            if entity.supporting_spans and (entity.entity_kind != "api_route" or len(entity.supporting_spans) > 16):
                raise ValueError("invalid supporting structural evidence")
            for span in entity.supporting_spans:
                if not 1 <= span.start_line <= span.end_line <= len(lines):
                    raise ValueError("supporting structural location is outside source text")
                supporting.append({"relative_path": entity.relative_path, "start_line": span.start_line,
                    "end_line": span.end_line, "precision": "exact", "role": span.role,
                    "decoded_snippet_hash": text_digest("".join(lines[span.start_line - 1:span.end_line]))})
            structural = entity.entity_kind in {"api_route", "dependency"} or (
                entity.entity_kind == "module" and "parser:lexical-fallback" in entity.evidence_refs)
            extra = {"observation_basis": {"api_route": "static_route_declaration",
                "dependency": "static_import_not_resolved_runtime_dependency", "module": "source_file_not_parsed_symbols"}[entity.entity_kind],
                "supporting_locators": supporting} if structural else {}
            observations.append(CodeEntityObservation(
                entity.provider_node_id, legacy_code_object_id(source.project_id, source.id, entity.provider_node_id), key,
                {
                    "schema": "nasus.code-entity-observation.v3" if structural else "nasus.code-entity-observation.v2",
                    "symbol": asdict(key), **extra,
                    "decoder_version": DECODER_VERSION,
                    "locator": {"relative_path": entity.relative_path, "start_line": entity.start_line,
                                "end_line": entity.end_line, "precision": "approximate" if approximate else "exact"},
                    "source_file_hash": unit.content_hash, "decoded_snippet_hash": snippet_hash,
                },
            ))
        return self.repository.register(source, observations, provider=result.provider,
                                        provider_version=result.provider_version, captured_at=captured_at)
