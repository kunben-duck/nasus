from __future__ import annotations

from collections.abc import Sequence

from apps.api.app.application.system_image.context_extraction import (
    ContextExtractionService,
)
from apps.api.app.application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeIntelligenceResult,
    CodeRelationshipCandidate,
    SourceTextUnit,
)
from apps.api.app.application.system_image.system_image_models import RawAssetRecord


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
