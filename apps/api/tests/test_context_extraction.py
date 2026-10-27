from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.context_extraction import (
    ContextAnchor, ContextExtractionService, ExtractedSourceContext,
)
from apps.api.app.application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeIntelligenceResult,
    CodeRelationshipCandidate,
    SourceTextUnit,
)
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.application.system_image.code_entity_registry import RegisteredCodeEntity
from apps.api.app.domain.system_image.code_identity import CodeSymbolKey
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.frozen_projection import require_frozen_projection
from apps.api.app.domain.system_image.entity_resolution import CrossSourceEntityResolver
from apps.api.app.domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest


class _SourceReader:
    def extract_text_units(self, source: RawAssetRecord) -> list[SourceTextUnit]:
        return [
            SourceTextUnit(
                relative_path="payments.py",
                text="def authorize():\n    return capture()\n",
                byte_count=38,
                content_hash="source-hash",
            )
        ]


class _DuplicateEdgeCodeIntelligence:
    def analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult:
        entities = (
            CodeEntityCandidate(
                provider_node_id="authorize",
                name="authorize",
                qualified_name="payments.authorize",
                entity_kind="function",
                relative_path="payments.py",
                language="python",
                start_line=1,
                end_line=2,
                evidence_refs=("file:payments.py#L1-L2",),
            ),
            CodeEntityCandidate(
                provider_node_id="capture",
                name="capture",
                qualified_name="payments.capture",
                entity_kind="function",
                relative_path="payments.py",
                language="python",
                start_line=4,
                end_line=5,
                evidence_refs=("file:payments.py#L4-L5",),
            ),
        )
        relationships = (
            CodeRelationshipCandidate(
                from_provider_node_id="authorize",
                relationship_kind="depends_on",
                to_provider_node_id="capture",
                confidence=0.82,
                evidence_refs=("code-graph-edge:CALLS",),
            ),
            CodeRelationshipCandidate(
                from_provider_node_id="authorize",
                relationship_kind="depends_on",
                to_provider_node_id="capture",
                confidence=0.91,
                evidence_refs=("code-graph-edge:USAGE",),
            ),
        )
        return CodeIntelligenceResult(
            provider="test-code-graph",
            provider_version="1",
            entities=entities,
            relationships=relationships,
            evidence_refs=("provider:test-code-graph",),
        )


def _extract(baseline_id: str):
    source = RawAssetRecord(
        id="raw_payments_code",
        project_id="project_payments",
        source_type="code",
        source_uri="/tmp/payments",
        ingestion_status="indexed",
    )
    return ContextExtractionService(
        _SourceReader(),
        _DuplicateEdgeCodeIntelligence(),
    ).extract(
        project_id="project_payments",
        project_name="Payments",
        baseline_id=baseline_id,
        sources=[source],
        version_id=None,
        captured_at="2026-08-09T00:00:00Z",
    )


def test_duplicate_provider_edges_are_coalesced_with_all_evidence() -> None:
    extracted = _extract("baseline_official")

    dependency_edges = [
        relationship
        for relationship in extracted.relationships
        if relationship.relationship_type == "depends_on"
    ]

    assert len(dependency_edges) == 1
    assert dependency_edges[0].confidence == 0.91
    assert "code-graph-edge:CALLS" in dependency_edges[0].source_refs
    assert "code-graph-edge:USAGE" in dependency_edges[0].source_refs
    assert len({relationship.id for relationship in extracted.relationships}) == len(
        extracted.relationships
    )


def test_relationship_identity_is_scoped_to_baseline() -> None:
    official = _extract("baseline_official")
    version = _extract("baseline_version_1")

    official_edge = next(
        relationship
        for relationship in official.relationships
        if relationship.relationship_type == "depends_on"
    )
    version_edge = next(
        relationship
        for relationship in version.relationships
        if relationship.relationship_type == "depends_on"
    )

    assert official_edge.id != version_edge.id


def frozen_extract(*, inventory=True, registration=True, analysis_id="analysis"):
    source = RawAssetRecord(id="raw_payments_code", project_id="project_payments", source_type="code",
        source_uri="/tmp/payments", ingestion_status="indexed")
    members = (SourceManifestMember("binding", "code", "source-revision", "captured"),)
    manifest = CapturedSourceManifest("manifest", source.project_id,
        snapshot_digest([asdict(member) for member in members]), "now", members)
    result = _DuplicateEdgeCodeIntelligence().analyze(())
    formal = replace(result.entities[0], symbol_key=CodeSymbolKey("payments.py", "python", "function", (), "authorize"),
        identity_status="exact", location_precision="exact")
    result = replace(result, entities=(formal, result.entities[1]))
    recorded = []

    def record(source, raw, units, **kwargs):
        recorded.append(raw)
        return analysis_id

    registry = SimpleNamespace(register=lambda *args, **kwargs: {
        "authorize": RegisteredCodeEntity("00000000-0000-4000-8000-000000000001", "entity-revision", "source-revision")})
    service = ContextExtractionService(_SourceReader(), SimpleNamespace(analyze=lambda units: result),
        code_entity_registry=registry if registration else None,
        code_analysis_inventory=SimpleNamespace(record=record) if inventory else None)
    context = service.extract(project_id=source.project_id, project_name="Payments", baseline_id="baseline",
        sources=[source], version_id=None, captured_at="now", source_manifest=manifest)
    return context, manifest, source, recorded, result


def test_frozen_membership_keeps_unresolved_provider_observations_in_inventory_not_fake_entities():
    context, manifest, source, recorded, raw = frozen_extract()
    assert recorded == [raw] and len(raw.entities) == 2 and len(raw.relationships) == 2
    assert source.evidence_refs == ["code-analysis:analysis", "code-intelligence:test-code-graph:1", "provider:test-code-graph"]
    assert [item.id for item in context.objects] == ["CODE-00000000-0000-4000-8000-000000000001"]
    assert context.relationships == []
    assert context.metrics[0].metrics["code_symbols"] == 1
    assert require_frozen_projection(manifest, "baseline", objects=context.objects,
        relationships=context.relationships, metrics=context.metrics).ready


@pytest.mark.parametrize("missing", ["inventory", "registration"])
def test_frozen_extraction_cannot_discard_unresolved_nodes_without_inventory_or_registry(missing):
    with pytest.raises(ImageRevisionIntegrityError):
        frozen_extract(**{missing: False})


@pytest.mark.parametrize("analysis_id", [None, "", " "])
def test_frozen_extraction_requires_inventory_receipt_not_only_a_recorder(analysis_id):
    with pytest.raises(ImageRevisionIntegrityError, match="persisted analysis report"):
        frozen_extract(analysis_id=analysis_id)


def test_frozen_extraction_does_not_promote_label_overlap_into_business_relations_or_coverage():
    sources = [RawAssetRecord(id="source_" + kind, project_id="project", source_type=kind,
        source_uri="/fixtures/" + kind, ingestion_status="indexed") for kind in ("code", "us_doc", "test_asset")]
    members = tuple(sorted((SourceManifestMember("binding_" + source.source_type, source.source_type,
        "revision_" + source.source_type, "captured") for source in sources), key=lambda item: item.binding_id))
    manifest = CapturedSourceManifest("manifest", "project", snapshot_digest([asdict(item) for item in members]), "now", members)
    calls = []

    class CountingResolver(CrossSourceEntityResolver):
        def resolve(self, candidates):
            calls.append(tuple(candidates))
            return super().resolve(candidates)

    service = ContextExtractionService(_SourceReader(), _DuplicateEdgeCodeIntelligence(), entity_resolver=CountingResolver())

    def extract_source(source, **kwargs):
        code = RegisteredCodeEntity("00000000-0000-4000-8000-000000000001", "entity-revision", "revision_code")
        document = SimpleNamespace(entity_id=source.source_type, kind="requirement" if source.source_type == "us_doc" else "test_case",
            document_revision_id="document_" + source.source_type,
            source_revision_id="revision_" + source.source_type, payload={"fields": [{"value": "Authorize payments"}]})
        return ExtractedSourceContext((ContextAnchor("Authorize payments", source.source_type,
            ("evidence_" + source.source_type,), source.id, code_reference=code if source.source_type == "code" else None,
            document_reference=document if source.source_type != "code" else None),))

    service._extract_source_context = extract_source
    inputs = dict(project_id="project", project_name="Payments", baseline_id="baseline", sources=sources,
        version_id=None, captured_at="now")
    legacy = service.extract(**inputs)
    assert {edge.relationship_type for edge in legacy.relationships} >= {"implements", "covers", "validates"}
    assert len(calls) == 1
    frozen = service.extract(**inputs, source_manifest=manifest)
    assert len(calls) == 1, "Frozen structure extraction must not perform unaudited semantic linking"
    assert len(frozen.objects) == 3 and frozen.relationships == []
    assert all(item.relations == [] for item in frozen.objects)
    assert require_frozen_projection(manifest, "baseline", objects=frozen.objects,
        relationships=frozen.relationships, metrics=frozen.metrics).ready
    metrics = {item.metric_group: item.metrics for item in frozen.metrics}
    assert metrics["code_quality"]["code_symbols"] == 1
    assert metrics["us_completion_quality"]["requirements_count"] == 1
    assert metrics["test_quality"]["test_count"] == 1
    assert all(item["measurement_basis"] == "admitted_projection_inventory_not_quality_assessment" for item in metrics.values())
    assert all(item["coverage_status"] == "unknown" for item in metrics.values())
    prohibited = {"critical_paths", "code_risk_score", "requirements_clarity", "traceability_coverage",
        "implemented_requirement_count", "test_covered_code_count", "validated_requirement_count",
        "scenario_coverage", "automation_coverage", "failed_runs", "cross_source_link_count"}
    assert all(not prohibited.intersection(item) for item in metrics.values())
