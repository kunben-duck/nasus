from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import json
from typing import Optional

from .source_snapshots import snapshot_digest


REFERENCE_METHOD = "nasus.explicit-requirement-reference.v1"
REFERENCE_IDS = re.compile(r"(?<![A-Za-z0-9_.-])(?:US|REQ)-[A-Za-z0-9][A-Za-z0-9_.-]*", re.I)


def requirement_references(text: str) -> tuple[str, ...]:
    return tuple(sorted({value.upper() for value in REFERENCE_IDS.findall(text)}))


@dataclass(frozen=True)
class ReferenceMention:
    external_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceDocument:
    object_id: str
    document_revision_id: str
    source_revision_id: str
    kind: str
    external_id: Optional[str]
    identity_status: str
    evidence_ids: tuple[str, ...]
    identity_evidence_ids: tuple[str, ...]
    mentions: tuple[ReferenceMention, ...]


@dataclass(frozen=True)
class ReferenceAssertion:
    subject_object_id: str
    subject_revision_id: str
    object_id: str
    object_revision_id: str
    reference_id: str
    subject_evidence_ids: tuple[str, ...]
    object_evidence_ids: tuple[str, ...]
    predicate: str = "references"
    semantic_kind: str = "observed"
    status: str = "proposed"
    applicability: str = "selected_manifest_only_not_business_coverage"


@dataclass(frozen=True)
class ReferenceGap:
    subject_object_id: str
    reference_id: str
    reason: str
    evidence_ids: tuple[str, ...]
    candidate_object_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceProposal:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    assertions: tuple[ReferenceAssertion, ...]
    gaps: tuple[ReferenceGap, ...]
    document_count: int
    method_version: str = REFERENCE_METHOD

    @property
    def digest(self) -> str:
        return snapshot_digest(asdict(self))


def propose_references(project_id: str, image_revision_id: str, image_artifact_hash: str,
                       documents: tuple[ReferenceDocument, ...]) -> ReferenceProposal:
    if len(documents) > 1000 or len({item.object_id for item in documents}) != len(documents):
        raise ValueError("invalid or oversized reference input")
    if sum(len(item.mentions) for item in documents) > 10000:
        raise ValueError("reference input exceeds proposal budget")
    targets: dict[str, list[ReferenceDocument]] = {}
    for item in documents:
        if item.kind == "requirement" and item.external_id:
            targets.setdefault(item.external_id.upper(), []).append(item)
    assertions, gaps = [], []
    for item in sorted(documents, key=lambda doc: doc.object_id):
        mentions: dict[str, set[str]] = {}
        for mention in item.mentions:
            if requirement_references(mention.external_id) != (mention.external_id,) or len(mention.external_id) > 128:
                raise ValueError("invalid exact requirement reference")
            if not mention.evidence_ids or not set(mention.evidence_ids).issubset(item.evidence_ids):
                raise ValueError("reference mention lacks frozen field evidence")
            mentions.setdefault(mention.external_id, set()).update(mention.evidence_ids)
        for ref, evidence in sorted(mentions.items()):
            candidates = sorted(targets.get(ref, []), key=lambda doc: doc.object_id)
            evidence_ids = tuple(sorted(evidence))
            reason = ("ambiguous_subject_identity" if item.identity_status == "ambiguous" else
                      "target_not_in_selected_image" if not candidates else
                      "ambiguous_reference_target" if len(candidates) != 1 or candidates[0].identity_status != "explicit_id" else
                      "self_reference" if candidates[0].object_id == item.object_id else
                      "target_evidence_missing" if not candidates[0].identity_evidence_ids else None)
            if reason:
                gaps.append(ReferenceGap(item.object_id, ref, reason, evidence_ids,
                                         tuple(doc.object_id for doc in candidates)))
                continue
            target = candidates[0]
            assertions.append(ReferenceAssertion(item.object_id, item.document_revision_id,
                target.object_id, target.document_revision_id, ref, evidence_ids, target.identity_evidence_ids))
    result = ReferenceProposal(project_id, image_revision_id, image_artifact_hash, tuple(assertions), tuple(gaps), len(documents))
    if len(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("reference proposal exceeds 4 MiB; no partial proposal was recorded")
    return result
