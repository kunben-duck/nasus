from __future__ import annotations

from dataclasses import asdict, dataclass

from .evidence import text_digest
from .semantic_link_input import SEMANTIC_LINK_METHOD, SemanticLinkInput
from .source_snapshots import snapshot_digest


@dataclass(frozen=True)
class SemanticCitation:
    span_id: str
    start: int
    end: int
    quote: str
    quote_hash: str


@dataclass(frozen=True)
class ExpectedOracle:
    span_id: str
    expected_value: str


@dataclass(frozen=True)
class LinkJudgment:
    subject_object_id: str
    subject_revision_id: str
    target_object_id: str
    target_revision_id: str
    relation: str
    assessment: str
    reason_summary: str
    evidence: tuple[SemanticCitation, ...]
    counterevidence: tuple[SemanticCitation, ...]
    unknowns: tuple[str, ...]
    oracle: ExpectedOracle | None


@dataclass(frozen=True)
class SemanticEvidenceAssessment:
    subject_object_id: str
    evidence_strength: str
    localization_quality: str
    ambiguity: str
    counterevidence_present: bool
    version_compatibility: str = "same_frozen_image"


@dataclass(frozen=True)
class SemanticEvaluation:
    input_digest: str
    judgments: tuple[LinkJudgment, ...]
    authority_object_id: str
    authority_revision_id: str
    evidence_assessments: tuple[SemanticEvidenceAssessment, ...]
    method_version: str = SEMANTIC_LINK_METHOD
    status: str = "proposed"
    semantic_kind: str = "inferred"
    authority_status: str = "pending_confirmation"
    authority_kind: str = "source_projection"
    calibrated_probability: None = None
    applicability: str = "selected_image_only_not_verified_coverage"

    @property
    def digest(self) -> str:
        return snapshot_digest(asdict(self))


def validate_judgments(prepared: SemanticLinkInput, input_digest: str,
                       judgments: tuple[LinkJudgment, ...]) -> SemanticEvaluation:
    if input_digest != prepared.digest:
        raise ValueError("semantic response input digest mismatch")
    if type(judgments) is not tuple or len(judgments) != len(prepared.subjects):
        raise ValueError("semantic response must assess every selected subject")
    subjects = {item.object_id: item for item in prepared.subjects}
    spans = {item.span_id: item for item in prepared.excerpts}
    if len({item.subject_object_id for item in judgments}) != len(judgments):
        raise ValueError("duplicate semantic judgment")
    assessments = []
    for item in judgments:
        subject = subjects.get(item.subject_object_id)
        if (subject is None or item.subject_revision_id != subject.revision_id
                or item.target_object_id != prepared.target.object_id
                or item.target_revision_id != prepared.target.revision_id or item.relation != prepared.relation):
            raise ValueError("semantic judgment endpoint mismatch")
        if item.assessment not in {"supports", "contradicts", "unrelated", "unknown"}:
            raise ValueError("unknown semantic assessment")
        if type(item.reason_summary) is not str or not item.reason_summary.strip() or len(item.reason_summary) > 1500:
            raise ValueError("semantic judgment requires a bounded reason")
        if (type(item.unknowns) is not tuple or len(item.unknowns) > 8
                or any(type(value) is not str or not value.strip() or len(value) > 1000 for value in item.unknowns)):
            raise ValueError("invalid semantic unknowns")
        if item.assessment == "unknown" and not item.unknowns:
            raise ValueError("unknown assessment must state the missing information")
        permitted = {subject.object_id, prepared.target.object_id}
        cited, counter = set(), set()
        seen = set()
        for citations, observed in ((item.evidence, cited), (item.counterevidence, counter)):
            if type(citations) is not tuple or len(citations) > 8:
                raise ValueError("invalid semantic citation budget")
            for citation in citations:
                span = spans.get(citation.span_id)
                if span is None or span.object_id not in permitted:
                    raise ValueError("citation is outside this endpoint pair")
                if (type(citation.start) is not int or type(citation.end) is not int
                        or not 0 <= citation.start < citation.end <= len(span.text)
                        or type(citation.quote) is not str or not citation.quote.strip()
                        or len(citation.quote) > 4096
                        or span.text[citation.start:citation.end] != citation.quote
                        or text_digest(citation.quote) != citation.quote_hash):
                    raise ValueError("citation does not match the exact verified text")
                identity = (citation.span_id, citation.start, citation.end)
                if identity in seen:
                    raise ValueError("duplicate or contradictory citation roles")
                seen.add(identity)
                observed.add(span.object_id)
        if item.assessment != "unknown" and cited | counter != permitted:
            raise ValueError("semantic judgment requires quotations from both endpoints")
        if item.assessment == "supports" and cited != permitted:
            raise ValueError("support requires positive evidence from both endpoints")
        if item.assessment == "contradicts" and not counter:
            raise ValueError("contradiction requires grounded counterevidence")
        if item.oracle is not None:
            span = spans.get(item.oracle.span_id)
            if (prepared.relation != "asserts" or span is None or span.object_id != subject.object_id
                    or span.role != "expected_result" or span.basis != "projected_field"
                    or item.oracle.expected_value != span.text
                    or not any(c.span_id == span.span_id for c in (*item.evidence, *item.counterevidence))):
                raise ValueError("oracle must quote an existing expected-result field")
        if item.assessment == "supports" and prepared.relation == "asserts" and item.oracle is None:
            raise ValueError("asserts support requires an explicit expected-result oracle")
        assessments.append(SemanticEvidenceAssessment(subject.object_id,
            "quoted_both_sides" if cited | counter == permitted else "insufficient_quotations",
            ("exact_source_and_verified_field" if prepared.relation == "implements" else "verified_projected_fields")
            if cited | counter == permitted else "incomplete",
            "unresolved" if item.unknowns else "requires_semantic_review", bool(counter)))
    return SemanticEvaluation(prepared.digest, tuple(sorted(judgments, key=lambda item: item.subject_object_id)),
                              prepared.target.object_id, prepared.target.revision_id,
                              tuple(sorted(assessments, key=lambda item: item.subject_object_id)))
