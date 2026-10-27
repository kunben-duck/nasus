from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ...domain.system_image.entity_resolution import (
    CrossSourceEntityResolver,
    EntityCandidate,
    ResolvedEntityLink,
)
from ...domain.system_image.code_alias import canonical_code_object_id
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, require_frozen_inputs
from .source_ports import (
    CodeIntelligencePort,
    CodeRelationshipCandidate,
    SourceIngestionPort,
    analyze_with_control,
    SourceCodeIntelligencePort,
)
from .system_image_models import ContextRelationship, KnowledgeCodeReference, KnowledgeDocumentReference, KnowledgeObject, QualityMetricSnapshot, RawAssetRecord
from .code_entity_registry import CodeEntityRegistryPort, CodeEntityRegistrationService, RegisteredCodeEntity, legacy_code_object_id
from .code_analysis_inventory import CodeAnalysisInventoryPort
from .document_projections import DocumentProjectionApplicationService, RegisteredDocument
from .build_lineage import CodeExtractionReceipt
from .source_ports import code_projection_payload
from ...domain.system_image.source_snapshots import snapshot_digest


@dataclass
class ExtractedContext:
    objects: list[KnowledgeObject] = field(default_factory=list)
    relationships: list[ContextRelationship] = field(default_factory=list)
    metrics: list[QualityMetricSnapshot] = field(default_factory=list)
    code_extractions: tuple[CodeExtractionReceipt, ...] = ()


@dataclass(frozen=True)
class ContextAnchor:
    name: str
    object_type: str
    evidence_refs: tuple[str, ...]
    source_id: str
    provider_node_id: str | None = None
    confidence: float = 0.74
    code_reference: RegisteredCodeEntity | None = None
    document_reference: RegisteredDocument | None = None

    @property
    def primary_evidence_ref(self) -> str:
        return self.evidence_refs[0] if self.evidence_refs else self.source_id


@dataclass(frozen=True)
class ExtractedSourceContext:
    anchors: tuple[ContextAnchor, ...]
    code_relationships: tuple[CodeRelationshipCandidate, ...] = ()
    code_extraction: CodeExtractionReceipt | None = None


class ContextExtractionService:
    def __init__(
        self,
        source_reader: SourceIngestionPort,
        code_intelligence: CodeIntelligencePort,
        entity_resolver: CrossSourceEntityResolver | None = None,
        code_entity_registry: CodeEntityRegistryPort | None = None,
        code_analysis_inventory: CodeAnalysisInventoryPort | None = None,
        document_projections: DocumentProjectionApplicationService | None = None,
        source_code_intelligence: Optional[SourceCodeIntelligencePort] = None,
    ) -> None:
        self._source_reader = source_reader
        self._code_intelligence = code_intelligence
        self._entity_resolver = entity_resolver or CrossSourceEntityResolver()
        self._code_entity_registration = CodeEntityRegistrationService(code_entity_registry) if code_entity_registry else None
        self._code_analysis_inventory = code_analysis_inventory
        self._document_projections = document_projections
        self._source_code_intelligence = source_code_intelligence

    def extract(
        self,
        *,
        project_id: str,
        project_name: str,
        baseline_id: str,
        sources: list[RawAssetRecord],
        version_id: str | None,
        captured_at: str,
        check_phase: Optional[Callable[[], None]] = None,
        invocation_id: Optional[str] = None,
        source_manifest: Optional[CapturedSourceManifest] = None,
    ) -> ExtractedContext:
        if source_manifest is not None:
            require_frozen_inputs(source_manifest)
            if source_manifest.project_id != project_id:
                raise ImageRevisionIntegrityError("Extraction project differs from its frozen manifest.")
        indexed_sources = [source for source in sources if source.ingestion_status == "indexed"]
        core = KnowledgeObject(
            id=f"CTX-{self._stable_id(project_id, 'core')}",
            name=f"{project_name} Core",
            type="System",
            branch="Official",
            confidence="0.80",
            relations=[],
            evidence=[source.id for source in indexed_sources],
            freshness="just now",
        )
        # Frozen candidates are rooted by SourceManifest/ImageRevision and their
        # provenance DAG. Keep the synthetic display node only in the legacy path.
        objects: list[KnowledgeObject] = [core] if source_manifest is None else []
        relationships: list[ContextRelationship] = []
        anchors_by_type: dict[str, list[ContextAnchor]] = {"code": [], "us_doc": [], "test_asset": []}
        entity_candidates: list[EntityCandidate] = []
        objects_by_id = {item.id: item for item in objects}
        provider_object_ids: dict[tuple[str, str], str] = {}
        code_extractions = []

        for source in indexed_sources:
            if check_phase is not None:
                check_phase()
            source_context = self._extract_source_context(source, captured_at=captured_at, check_phase=check_phase,
                                                         invocation_id=invocation_id,
                                                         frozen=source_manifest is not None)
            if source_context.code_extraction is not None:
                code_extractions.append(source_context.code_extraction)
            anchors = list(source_context.anchors)
            anchors_by_type[source.source_type].extend(anchors)
            for anchor in anchors:
                canonical_seed = anchor.provider_node_id or (
                    f"{anchor.name}|{anchor.primary_evidence_ref}"
                )
                object_id = f"CTX-{self._stable_id(project_id, source.id, canonical_seed)}"
                if anchor.provider_node_id:
                    object_id = legacy_code_object_id(project_id, source.id, anchor.provider_node_id)
                if anchor.code_reference:
                    object_id = canonical_code_object_id(anchor.code_reference.entity_id)
                if anchor.document_reference:
                    object_id = f"DOC-{anchor.document_reference.entity_id}"
                relation_name = core.name
                obj = KnowledgeObject(
                    id=object_id,
                    name=anchor.name,
                    type=anchor.object_type,
                    branch="Official",
                    confidence=f"{anchor.confidence:.2f}",
                    relations=[relation_name] if source_manifest is None else [],
                    evidence=list(dict.fromkeys((*anchor.evidence_refs, source.id))),
                    freshness="just now",
                    code_reference=KnowledgeCodeReference(
                        entity_id=anchor.code_reference.entity_id,
                        entity_revision_id=anchor.code_reference.entity_revision_id,
                        source_revision_id=anchor.code_reference.source_revision_id,
                    ) if anchor.code_reference else None,
                    document_reference=KnowledgeDocumentReference(
                        document_revision_id=anchor.document_reference.document_revision_id,
                        source_revision_id=anchor.document_reference.source_revision_id,
                    ) if anchor.document_reference else None,
                )
                if obj.id in objects_by_id:
                    raise ValueError("duplicate canonical object identity in materialization")
                objects.append(obj)
                objects_by_id[obj.id] = obj
                if anchor.provider_node_id:
                    provider_object_ids[(source.id, anchor.provider_node_id)] = obj.id
                entity_candidates.append(
                    EntityCandidate(
                        object_id=obj.id,
                        entity_kind=source.source_type,
                        label=" ".join([anchor.name, *(field["value"] for field in anchor.document_reference.payload["fields"])])
                              if anchor.document_reference else anchor.name,
                        evidence_refs=(source.id, *anchor.evidence_refs),
                    )
                )
                if source_manifest is None:
                    relationships.append(
                        ContextRelationship(
                            id=self._relationship_id(
                                project_id,
                                baseline_id,
                                object_id,
                                self._relationship_for_source(source.source_type),
                                core.id,
                            ),
                            project_id=project_id,
                            baseline_id=baseline_id,
                            from_object_id=obj.id,
                            relationship_type=self._relationship_for_source(source.source_type),
                            to_object_id=core.id,
                            confidence=min(0.86, anchor.confidence),
                            source_refs=list(
                                dict.fromkeys((source.id, *anchor.evidence_refs))
                            ),
                        ),
                    )
            relationships.extend(
                self._code_relationships(
                    project_id=project_id,
                    baseline_id=baseline_id,
                    source=source,
                    candidates=source_context.code_relationships,
                    provider_object_ids=provider_object_ids,
                    objects_by_id=objects_by_id,
                )
            )

        # Label overlap is a legacy navigation hint, not an evidenced business
        # relation. Frozen images admit cross-source assertions separately.
        resolved_links = self._entity_resolver.resolve(entity_candidates) if source_manifest is None else []
        relationships.extend(
            self._resolved_relationship(
                project_id=project_id,
                baseline_id=baseline_id,
                link=link,
            )
            for link in resolved_links
        )
        self._attach_relation_names(objects_by_id, resolved_links)
        metrics = self._inventory_metrics(
            manifest=source_manifest,
            baseline_id=baseline_id,
            version_id=version_id,
            captured_at=captured_at,
            anchors_by_type=anchors_by_type,
            relationship_count=len(self._coalesce_relationships(relationships)),
            source_ids=[source.id for source in indexed_sources],
        ) if source_manifest is not None else self._metrics(
            project_id=project_id,
            baseline_id=baseline_id,
            version_id=version_id,
            captured_at=captured_at,
            code_count=len(anchors_by_type["code"]),
            us_count=len(anchors_by_type["us_doc"]),
            test_count=len(anchors_by_type["test_asset"]),
            source_ids=[source.id for source in indexed_sources],
            resolved_links=resolved_links,
        )
        if source_manifest is None:
            core.relations = [item.name for item in objects[1:8]]
        return ExtractedContext(
            objects=objects,
            relationships=self._coalesce_relationships(relationships),
            metrics=metrics,
            code_extractions=tuple(code_extractions),
        )

    def _extract_source_context(self, source: RawAssetRecord, *, captured_at: str,
                                check_phase: Optional[Callable[[], None]] = None,
                                invocation_id: Optional[str] = None,
                                frozen: bool = False) -> ExtractedSourceContext:
        if frozen and source.source_type == "code" and self._code_entity_registration is None:
            raise ImageRevisionIntegrityError("Frozen code extraction requires the canonical entity registry.")
        units = self._source_reader.extract_text_units(source)
        if check_phase is not None:
            check_phase()
        if source.source_type == "code":
            if self._source_code_intelligence is not None and invocation_id and check_phase is not None:
                result = self._source_code_intelligence.analyze_source(source, units,
                    invocation_id=invocation_id, check_current=check_phase)
            else:
                result = (analyze_with_control(self._code_intelligence, units, check_phase)
                          if check_phase is not None else self._code_intelligence.analyze(units))
            analysis_id = None
            if self._code_analysis_inventory is not None:
                analysis_id = self._code_analysis_inventory.record(source, result, units, captured_at=captured_at)
            if any(item.status == "failed" for item in result.file_analyses):
                raise RuntimeError(f"code analysis contains failed files; analysis_id={analysis_id or 'unarchived'}")
            if analysis_id is not None:
                source.evidence_refs = list(dict.fromkeys((*source.evidence_refs, f"code-analysis:{analysis_id}")))
            registered: dict[str, RegisteredCodeEntity] = {}
            if self._code_entity_registration is not None:
                registered = self._code_entity_registration.register(source, result, units, captured_at=captured_at)
            if frozen and any(entity.provider_node_id not in registered for entity in result.entities) and (
                not isinstance(analysis_id, str) or not analysis_id.strip()
            ):
                raise ImageRevisionIntegrityError("Unregistered code observations require a persisted analysis report.")
            provider_ref = f"code-intelligence:{result.provider}:{result.provider_version}"
            source.evidence_refs = list(
                dict.fromkeys((*source.evidence_refs, provider_ref, *result.evidence_refs))
            )
            anchors = tuple(
                ContextAnchor(
                    name=self._code_entity_name(
                        entity.name,
                        entity.relative_path,
                        entity.entity_kind,
                    ),
                    object_type=self._code_object_type(entity.entity_kind),
                    evidence_refs=tuple(
                        dict.fromkeys((*entity.evidence_refs, provider_ref))
                    ),
                    source_id=source.id,
                    provider_node_id=entity.provider_node_id,
                    code_reference=registered.get(entity.provider_node_id),
                    confidence=(
                        0.62
                        if "parser:lexical-fallback" in entity.evidence_refs
                        else 0.92
                    ),
                )
                for entity in result.entities
                # Unresolved observations remain in the analysis inventory, not
                # as invented identities in the frozen formal membership.
                if not frozen or entity.provider_node_id in registered
            )
            return ExtractedSourceContext(
                anchors=anchors,
                code_relationships=result.relationships,
                code_extraction=CodeExtractionReceipt(source.id, analysis_id,
                    snapshot_digest(code_projection_payload(result)), result.execution_pin) if analysis_id else None,
            )

        if self._document_projections is not None:
            documents = self._document_projections.extract(source, units, captured_at=captured_at)
            return ExtractedSourceContext(anchors=tuple(ContextAnchor(
                name=item.title, object_type={"requirement": "USWorkItem", "test_case": "TestCase", "test_script": "TestCase",
                    "acceptance_criterion": "SourceAcceptanceCriterion", "business_rule": "SourceBusinessRule",
                    "requirement_document": "RequirementDocument", "test_document": "TestAsset"}[item.kind],
                evidence_refs=tuple(f"evidence:{key}" for key in item.evidence_ids), source_id=source.id,
                document_reference=item,
            ) for item in documents))

        anchors: list[ContextAnchor] = []
        for unit in units:
            relative = unit.relative_path
            text = unit.text
            evidence_ref = f"file:{relative}"
            if source.source_type == "us_doc":
                anchors.extend(self._us_anchors(text, relative, source.id, evidence_ref))
            else:
                anchors.extend(self._test_anchors(text, relative, source.id, evidence_ref))
        return ExtractedSourceContext(anchors=tuple(anchors))

    @staticmethod
    def _us_anchors(text: str, relative: str, source_id: str, evidence_ref: str) -> list[ContextAnchor]:
        anchors: list[ContextAnchor] = []
        for line in text.splitlines():
            stripped = line.strip(" #\t")
            if not stripped:
                continue
            if re.search(r"\bUS[-_ ]?\d+\b", stripped, re.IGNORECASE) or stripped.lower().startswith("as a "):
                anchors.append(ContextAnchor(stripped[:120], "USWorkItem", (evidence_ref,), source_id))
            elif line.startswith("#"):
                anchors.append(ContextAnchor(stripped[:120], "RequirementSection", (evidence_ref,), source_id))
        return anchors or [ContextAnchor(relative, "RequirementDocument", (evidence_ref,), source_id)]

    @staticmethod
    def _test_anchors(text: str, relative: str, source_id: str, evidence_ref: str) -> list[ContextAnchor]:
        names = re.findall(r"\bdef\s+(test_[A-Za-z0-9_]+)", text)
        names.extend(re.findall(r"\b(?:test|it)\s*\(\s*['\"]([^'\"]+)['\"]", text))
        return [
            ContextAnchor(f"{name} ({relative})", "TestCase", (evidence_ref,), source_id)
            for name in dict.fromkeys(names)
        ] or [ContextAnchor(relative, "TestAsset", (evidence_ref,), source_id)]

    @staticmethod
    def _code_entity_name(name: str, relative_path: str, entity_kind: str) -> str:
        if entity_kind == "module":
            return relative_path
        return f"{name} ({relative_path})"

    @staticmethod
    def _code_object_type(entity_kind: str) -> str:
        return {
            "module": "CodeModule",
            "class": "CodeClass",
            "interface": "CodeInterface",
            "enum": "CodeEnum",
            "function": "CodeFunction",
            "method": "CodeMethod",
            "api_route": "APIEndpoint",
            "dependency": "CodeDependency",
        }.get(entity_kind, "CodeSymbol")

    @classmethod
    def _code_relationships(
        cls,
        *,
        project_id: str,
        baseline_id: str,
        source: RawAssetRecord,
        candidates: tuple[CodeRelationshipCandidate, ...],
        provider_object_ids: dict[tuple[str, str], str],
        objects_by_id: dict[str, KnowledgeObject],
    ) -> list[ContextRelationship]:
        relationships: list[ContextRelationship] = []
        for candidate in candidates:
            from_object_id = provider_object_ids.get(
                (source.id, candidate.from_provider_node_id)
            )
            to_object_id = provider_object_ids.get(
                (source.id, candidate.to_provider_node_id)
            )
            if not from_object_id or not to_object_id or from_object_id == to_object_id:
                continue
            relationship_type = cls._code_relationship_type(
                candidate.relationship_kind
            )
            relationship = ContextRelationship(
                id=cls._relationship_id(
                    project_id,
                    baseline_id,
                    from_object_id,
                    relationship_type,
                    to_object_id,
                ),
                project_id=project_id,
                baseline_id=baseline_id,
                from_object_id=from_object_id,
                relationship_type=relationship_type,
                to_object_id=to_object_id,
                confidence=candidate.confidence,
                source_refs=list(
                    dict.fromkeys((source.id, *candidate.evidence_refs))
                ),
            )
            relationships.append(relationship)
            cls._attach_relationship_names(objects_by_id, relationship)
        return relationships

    @staticmethod
    def _code_relationship_type(relationship_kind: str) -> str:
        if relationship_kind == "belongs_to":
            return "belongs_to"
        return "depends_on"

    @staticmethod
    def _attach_relationship_names(
        objects_by_id: dict[str, KnowledgeObject],
        relationship: ContextRelationship,
    ) -> None:
        source = objects_by_id.get(relationship.from_object_id)
        target = objects_by_id.get(relationship.to_object_id)
        if source is None or target is None:
            return
        if target.name not in source.relations:
            source.relations.append(target.name)

    @staticmethod
    def _inventory_metrics(
        *,
        manifest: CapturedSourceManifest,
        baseline_id: str,
        version_id: str | None,
        captured_at: str,
        anchors_by_type: dict[str, list[ContextAnchor]],
        relationship_count: int,
        source_ids: list[str],
    ) -> list[QualityMetricSnapshot]:
        def count(source_type, kind):
            return sum(anchor.document_reference.kind == kind for anchor in anchors_by_type[source_type]
                       if anchor.document_reference is not None)

        common = {
            "measurement_basis": "admitted_projection_inventory_not_quality_assessment",
            "coverage_status": "unknown",
            "source_manifest_id": manifest.manifest_id,
            "source_manifest_hash": manifest.content_hash,
        }
        groups = (
            ("code", "code_quality", {"code_symbols": len(anchors_by_type["code"]),
                "structural_relationship_count": relationship_count}),
            ("us", "us_completion_quality", {"requirements_count": count("us_doc", "requirement"),
                "acceptance_criterion_count": count("us_doc", "acceptance_criterion"),
                "business_rule_count": count("us_doc", "business_rule")}),
            ("tests", "test_quality", {"test_count": count("test_asset", "test_case") + count("test_asset", "test_script"),
                "test_case_count": count("test_asset", "test_case"), "test_script_count": count("test_asset", "test_script")}),
        )
        return [QualityMetricSnapshot(id=f"metric_{manifest.project_id}_{suffix}", project_id=manifest.project_id,
            baseline_id=baseline_id, version_id=version_id, metric_group=group, metrics={**common, **values},
            evidence_refs=source_ids, captured_at=captured_at) for suffix, group, values in groups]

    @staticmethod
    def _metrics(
        *,
        project_id: str,
        baseline_id: str,
        version_id: str | None,
        captured_at: str,
        code_count: int,
        us_count: int,
        test_count: int,
        source_ids: list[str],
        resolved_links: list[ResolvedEntityLink],
    ) -> list[QualityMetricSnapshot]:
        implemented_requirements = {
            item.to_object_id
            for item in resolved_links
            if item.relationship_type == "implements"
        }
        validated_requirements = {
            item.to_object_id
            for item in resolved_links
            if item.relationship_type == "validates"
        }
        covered_code_objects = {
            item.to_object_id
            for item in resolved_links
            if item.relationship_type == "covers"
        }
        traced_requirements = implemented_requirements | validated_requirements
        coverage = min(1.0, len(traced_requirements) / max(us_count, 1)) if us_count else 0.0
        automation = min(1.0, len(covered_code_objects) / max(code_count, 1)) if code_count else 0.0
        return [
            QualityMetricSnapshot(
                id=f"metric_{project_id}_code",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="code_quality",
                metrics={
                    "code_symbols": code_count,
                    "critical_paths": min(code_count, 5),
                    "code_risk_score": max(10, 70 - code_count),
                    "implemented_requirement_count": len(implemented_requirements),
                    "test_covered_code_count": len(covered_code_objects),
                },
                evidence_refs=source_ids,
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_us",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="us_completion_quality",
                metrics={
                    "requirements_count": us_count,
                    "requirements_clarity": min(0.95, 0.55 + us_count * 0.08),
                    "traceability_coverage": coverage,
                    "validated_requirement_count": len(validated_requirements),
                },
                evidence_refs=source_ids,
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_tests",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="test_quality",
                metrics={
                    "test_count": test_count,
                    "scenario_coverage": coverage,
                    "automation_coverage": automation,
                    "failed_runs": 0,
                    "cross_source_link_count": len(resolved_links),
                },
                evidence_refs=source_ids,
                captured_at=captured_at,
            ),
        ]

    @staticmethod
    def _resolved_relationship(
        *,
        project_id: str,
        baseline_id: str,
        link: ResolvedEntityLink,
    ) -> ContextRelationship:
        return ContextRelationship(
            id=ContextExtractionService._relationship_id(
                project_id,
                baseline_id,
                link.from_object_id,
                link.relationship_type,
                link.to_object_id,
            ),
            project_id=project_id,
            baseline_id=baseline_id,
            from_object_id=link.from_object_id,
            relationship_type=link.relationship_type,
            to_object_id=link.to_object_id,
            confidence=link.confidence,
            source_refs=list(link.source_refs),
        )

    @staticmethod
    def _attach_relation_names(
        objects_by_id: dict[str, KnowledgeObject],
        links: list[ResolvedEntityLink],
    ) -> None:
        for link in links:
            source = objects_by_id.get(link.from_object_id)
            target = objects_by_id.get(link.to_object_id)
            if source is None or target is None:
                continue
            if target.name not in source.relations:
                source.relations.append(target.name)
            if source.name not in target.relations:
                target.relations.append(source.name)

    @staticmethod
    def _relationship_for_source(source_type: str) -> str:
        if source_type == "code":
            return "implements"
        if source_type == "us_doc":
            return "impacts"
        return "covers"

    @classmethod
    def _relationship_id(
        cls,
        project_id: str,
        baseline_id: str,
        from_object_id: str,
        relationship_type: str,
        to_object_id: str,
    ) -> str:
        return f"rel_{cls._stable_id(project_id, baseline_id, from_object_id, relationship_type, to_object_id)}"

    @staticmethod
    def _coalesce_relationships(
        relationships: list[ContextRelationship],
    ) -> list[ContextRelationship]:
        """Merge provider edges that normalize to the same domain relationship."""

        merged: dict[str, ContextRelationship] = {}
        for relationship in relationships:
            current = merged.get(relationship.id)
            if current is None:
                merged[relationship.id] = relationship.model_copy(deep=True)
                continue
            current.confidence = max(current.confidence, relationship.confidence)
            current.source_refs = list(
                dict.fromkeys((*current.source_refs, *relationship.source_refs))
            )
        return list(merged.values())

    @staticmethod
    def _stable_id(*parts: str) -> str:
        raw = "|".join(parts)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16].upper()
