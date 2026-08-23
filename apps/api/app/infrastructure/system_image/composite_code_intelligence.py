from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from ...application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeIntelligencePort,
    CodeIntelligenceResult,
    CodeRelationshipCandidate,
    SourceTextUnit,
)
from ..config.code_graph_config import CodeGraphMode
from .codebase_memory_code_intelligence import CodebaseMemoryError


class CompositeCodeIntelligenceAdapter:
    """Combines canonical structural facts with a replaceable graph projection."""

    def __init__(
        self,
        primary: CodeIntelligencePort,
        enhancer: CodeIntelligencePort | None,
        *,
        mode: CodeGraphMode,
    ) -> None:
        self.primary = primary
        self.enhancer = enhancer
        self.mode = mode

    def analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult:
        primary = self.primary.analyze(units)
        if self.mode == "disabled":
            return replace(
                primary,
                evidence_refs=self._union(primary.evidence_refs, ("code-graph:disabled",)),
            )
        if self.enhancer is None:
            if self.mode == "required":
                raise CodebaseMemoryError("required code graph adapter is not configured")
            return self._unavailable(primary, "not-configured")

        try:
            enhanced = self.enhancer.analyze(units)
        except CodebaseMemoryError:
            if self.mode == "required":
                raise
            return self._unavailable(primary, "provider-unavailable")
        return self._merge(primary, enhanced)

    def diagnostics(self) -> dict[str, str]:
        primary_details = self._adapter_diagnostics(self.primary)
        details = {
            "backend": primary_details.get("backend", "tree-sitter"),
            "version": primary_details.get("version", "unknown"),
            "graph_mode": self.mode,
        }
        if self.mode == "disabled":
            return {
                **details,
                "graph_backend": "disabled",
                "graph_status": "disabled",
            }
        if self.enhancer is None:
            if self.mode == "required":
                raise CodebaseMemoryError("required code graph adapter is not configured")
            return {
                **details,
                "graph_backend": "unconfigured",
                "graph_status": "unavailable",
            }
        enhancer_details = self._adapter_diagnostics(self.enhancer)
        if enhancer_details.get("graph_status") != "ready" and self.mode == "required":
            raise CodebaseMemoryError("required code graph provider is unavailable")
        return {**details, **enhancer_details}

    @classmethod
    def _merge(
        cls,
        primary: CodeIntelligenceResult,
        enhanced: CodeIntelligenceResult,
    ) -> CodeIntelligenceResult:
        entities = list(primary.entities)
        provider_ids = {item.provider_node_id: item.provider_node_id for item in primary.entities}
        strict_index = {cls._entity_key(item): index for index, item in enumerate(entities)}
        loose_candidates: dict[tuple[str, str, str], list[int]] = {}
        for index, entity in enumerate(entities):
            loose_candidates.setdefault(cls._loose_entity_key(entity), []).append(index)

        for candidate in enhanced.entities:
            index = strict_index.get(cls._entity_key(candidate))
            if index is None:
                matches = loose_candidates.get(cls._loose_entity_key(candidate), [])
                index = matches[0] if len(matches) == 1 else None
            if index is None:
                index = len(entities)
                entities.append(candidate)
                strict_index[cls._entity_key(candidate)] = index
                loose_candidates.setdefault(cls._loose_entity_key(candidate), []).append(index)
            else:
                retained = entities[index]
                entities[index] = replace(
                    retained,
                    evidence_refs=cls._union(
                        retained.evidence_refs,
                        candidate.evidence_refs,
                    ),
                )
            provider_ids[candidate.provider_node_id] = entities[index].provider_node_id

        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate] = {}
        for relation in (*primary.relationships, *enhanced.relationships):
            source_id = provider_ids.get(relation.from_provider_node_id)
            target_id = provider_ids.get(relation.to_provider_node_id)
            if source_id is None or target_id is None or source_id == target_id:
                continue
            key = (source_id, relation.relationship_kind, target_id)
            mapped = replace(
                relation,
                from_provider_node_id=source_id,
                to_provider_node_id=target_id,
            )
            existing = relationships.get(key)
            if existing is None:
                relationships[key] = mapped
            else:
                relationships[key] = replace(
                    existing,
                    confidence=max(existing.confidence, mapped.confidence),
                    evidence_refs=cls._union(
                        existing.evidence_refs,
                        mapped.evidence_refs,
                    ),
                )

        return CodeIntelligenceResult(
            provider=f"{primary.provider}+{enhanced.provider}",
            provider_version=f"{primary.provider_version}|{enhanced.provider_version}",
            entities=tuple(entities),
            relationships=tuple(relationships.values()),
            evidence_refs=cls._union(
                primary.evidence_refs,
                enhanced.evidence_refs,
                ("code-graph:enriched",),
            ),
            unsupported_paths=primary.unsupported_paths,
        )

    @staticmethod
    def _unavailable(
        primary: CodeIntelligenceResult,
        reason: str,
    ) -> CodeIntelligenceResult:
        return replace(
            primary,
            evidence_refs=CompositeCodeIntelligenceAdapter._union(
                primary.evidence_refs,
                ("code-graph:unavailable", f"code-graph-reason:{reason}"),
            ),
        )

    @staticmethod
    def _entity_key(entity: CodeEntityCandidate) -> tuple[str, str, int, str]:
        return (
            entity.relative_path.replace("\\", "/").casefold(),
            entity.entity_kind,
            entity.start_line,
            entity.name.casefold(),
        )

    @staticmethod
    def _loose_entity_key(entity: CodeEntityCandidate) -> tuple[str, str, str]:
        return (
            entity.relative_path.replace("\\", "/").casefold(),
            entity.entity_kind,
            entity.name.casefold(),
        )

    @staticmethod
    def _adapter_diagnostics(adapter: object) -> dict[str, str]:
        diagnostics = getattr(adapter, "diagnostics", None)
        if callable(diagnostics):
            result = diagnostics()
            if isinstance(result, dict):
                return {str(key): str(value) for key, value in result.items()}
        return {
            "backend": str(getattr(adapter, "provider", "unknown")),
            "version": str(getattr(adapter, "provider_version", "unknown")),
        }

    @staticmethod
    def _union(*groups: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item for group in groups for item in group))


__all__ = ["CompositeCodeIntelligenceAdapter"]
