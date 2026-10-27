from __future__ import annotations

from dataclasses import replace
from itertools import chain
from typing import Callable, Sequence

from ...application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeIntelligencePort,
    CodeIntelligenceResult,
    CodeIntelligenceUnavailable,
    CodeRelationshipCandidate,
    SourceTextUnit,
    analyze_with_control,
)
from ..config.code_graph_config import CodeGraphMode
from ...domain.system_image.code_identity import CodeSymbolKey
from ...domain.system_image.code_provider import CodeProjectionGap, CodeProviderCapabilities, CodeProviderObservation
from .codebase_memory_code_intelligence import CodebaseMemoryError
from .code_identity_normalization import attach_symbol_keys
from .code_graph_observation_validation import validate_java_imports


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
        return self._analyze(units)

    def capabilities(self) -> CodeProviderCapabilities:
        declaration = self._declaration(self.primary)
        return CodeProviderCapabilities("nasus-composite", "1", ("capabilities", "analyze", "analyze_controlled"),
            declaration.languages, declaration.language_coverage)

    def analyze_controlled(self, units: Sequence[SourceTextUnit], *, check_current: Callable[[], None]) -> CodeIntelligenceResult:
        return self._analyze(units, check_current=check_current)

    def _analyze(self, units: Sequence[SourceTextUnit], *, check_current=None) -> CodeIntelligenceResult:
        def analyze(adapter):
            if check_current is not None:
                return analyze_with_control(adapter, units, check_current)
            return adapter.analyze(units)

        primary = analyze(self.primary)
        if any(item.status == "failed" for item in primary.file_analyses):
            # Preserve diagnostics for the failed materialization even when a
            # required graph provider would also fail on the invalid source.
            return self._not_observed(replace(primary,
                evidence_refs=self._union(primary.evidence_refs, ("code-graph:skipped:parse-failure",))),
                "not_run", "source_parse_failure")
        if self.mode == "disabled":
            return self._not_observed(replace(
                primary,
                evidence_refs=self._union(primary.evidence_refs, ("code-graph:disabled",)),
            ), "not_run", "graph_disabled_by_policy")
        if self.enhancer is None:
            if self.mode == "required":
                raise CodebaseMemoryError("required code graph adapter is not configured")
            return self._unavailable(primary, "not-configured")

        try:
            enhanced = analyze(self.enhancer)
            return self._merge(primary, validate_java_imports(attach_symbol_keys(enhanced, primary), primary))
        except CodeIntelligenceUnavailable:
            if self.mode == "required":
                raise
            return self._unavailable(primary, "provider-unavailable")

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
        failed_paths = {item.relative_path for item in primary.file_analyses if item.status == "failed"}
        if failed_paths:
            allowed = {item.provider_node_id for item in enhanced.entities if item.relative_path not in failed_paths}
            enhanced = replace(enhanced, entities=tuple(item for item in enhanced.entities if item.provider_node_id in allowed),
                               relationships=tuple(item for item in enhanced.relationships
                                                   if item.from_provider_node_id in allowed and item.to_provider_node_id in allowed))
        for result in (primary, enhanced):
            if len({item.provider_node_id for item in result.entities}) != len(result.entities):
                raise CodebaseMemoryError("code graph contains duplicate provider node IDs")
        entities = list(primary.entities)
        primary_ids = {item.provider_node_id: item.provider_node_id for item in primary.entities}
        used_ids = set(primary_ids)
        enhanced_ids: dict[str, str] = {}
        canonical_index: dict[CodeSymbolKey, list[int]] = {}
        strict_index: dict[tuple[str, str, str, int, int, str], list[int]] = {}
        for index, entity in enumerate(entities):
            strict_index.setdefault(cls._entity_key(entity), []).append(index)
            if entity.symbol_key is not None:
                canonical_index.setdefault(entity.symbol_key, []).append(index)

        for candidate in enhanced.entities:
            original_provider_id = candidate.provider_node_id
            matches = canonical_index.get(candidate.symbol_key, []) if candidate.symbol_key else []
            if not matches and candidate.identity_status != "ambiguous":
                # Non-symbol observations need identical, precise source spans.
                # Approximate line 1 must never act as a unique identity key.
                if candidate.location_precision == "exact":
                    matches = [index for index in strict_index.get(cls._entity_key(candidate), [])
                               if entities[index].identity_status != "ambiguous"
                               and (candidate.symbol_key is None or entities[index].symbol_key == candidate.symbol_key)]
            index = matches[0] if len(matches) == 1 else None
            if index is None:
                index = len(entities)
                # Provider IDs are namespaced by result, not assumed globally unique.
                while candidate.provider_node_id in used_ids:
                    candidate = replace(candidate, provider_node_id=f"enhancer:{index}:{candidate.provider_node_id}")
                used_ids.add(candidate.provider_node_id)
                entities.append(candidate)
            else:
                retained = entities[index]
                entities[index] = replace(
                    retained,
                    evidence_refs=cls._union(
                        retained.evidence_refs,
                        candidate.evidence_refs,
                    ),
                )
            enhanced_ids[original_provider_id] = entities[index].provider_node_id

        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate] = {}
        for relation, provider_ids in chain(
            ((item, primary_ids) for item in primary.relationships),
            ((item, enhanced_ids) for item in enhanced.relationships),
        ):
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
            file_analyses=primary.file_analyses,
            structural_facts=primary.structural_facts,
            provider_observations=(*primary.provider_observations, *enhanced.provider_observations),
            native_query_observations=(*primary.native_query_observations, *enhanced.native_query_observations),
            execution_pin=enhanced.execution_pin,
        )

    def _unavailable(
        self,
        primary: CodeIntelligenceResult,
        reason: str,
    ) -> CodeIntelligenceResult:
        return self._not_observed(replace(
            primary,
            evidence_refs=CompositeCodeIntelligenceAdapter._union(
                primary.evidence_refs,
                ("code-graph:unavailable", f"code-graph-reason:{reason}"),
            ),
        ), "unavailable", reason)

    @staticmethod
    def _declaration(adapter) -> CodeProviderCapabilities:
        capabilities = getattr(adapter, "capabilities", None)
        if callable(capabilities):
            declaration = capabilities()
            if not isinstance(declaration, CodeProviderCapabilities):
                raise CodebaseMemoryError("invalid code provider declaration")
            return declaration
        return CodeProviderCapabilities(str(getattr(adapter, "provider", "external-code-graph")), "undeclared", ())

    def _not_observed(self, primary, availability, reason):
        observation = CodeProviderObservation(self._declaration(self.enhancer), 0, 0, 0, 0,
            "not_run", "not_run", (CodeProjectionGap(reason),), availability)
        return replace(primary, provider_observations=(*primary.provider_observations, observation))

    @staticmethod
    def _entity_key(entity: CodeEntityCandidate) -> tuple[str, str, str, int, int, str]:
        return (
            entity.relative_path,
            entity.language,
            entity.entity_kind,
            entity.start_line,
            entity.end_line,
            entity.name,
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
