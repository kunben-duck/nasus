from __future__ import annotations

from dataclasses import asdict, dataclass

from .image_revision import ImageRevisionIntegrityError, require_digest
from .source_snapshots import snapshot_digest


REVIEWED_IMAGE_POLICY = "nasus.image-candidate.v2"
FREEZE_LINKS_TOOL = "system_image.revisions.freeze_links"


@dataclass(frozen=True)
class ImageAssertionMember:
    assertion_id: str
    proposal_id: str
    origin_image_revision_id: str
    proposal_digest: str
    assertion_digest: str
    evidence_digest: str
    decision_id: str
    decision_digest: str
    decision: str
    subject_object_id: str
    subject_revision_id: str
    object_id: str
    object_revision_id: str
    subject_evidence_ids: tuple[str, ...]
    object_evidence_ids: tuple[str, ...]
    predicate: str = "references"
    applicability: str = "selected_manifest_only_not_business_coverage"

    def __post_init__(self):
        for key in ("assertion_id", "proposal_id", "origin_image_revision_id", "decision_id",
                    "subject_object_id", "subject_revision_id", "object_id", "object_revision_id"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError("invalid assertion membership identity")
        for key in ("proposal_digest", "assertion_digest", "evidence_digest", "decision_digest"):
            require_digest(getattr(self, key))
        if (self.decision not in {"accept", "reject", "defer"} or self.predicate != "references"
                or self.applicability != "selected_manifest_only_not_business_coverage"):
            raise ValueError("invalid reference membership semantics")
        for values in (self.subject_evidence_ids, self.object_evidence_ids):
            if (not isinstance(values, tuple) or not values or len(values) > 100 or len(set(values)) != len(values)
                    or any(not isinstance(value, str) or not value or len(value) > 128 for value in values)):
                raise ValueError("invalid assertion evidence membership")


def assertion_member(value: dict) -> ImageAssertionMember:
    return ImageAssertionMember(**{**value, "subject_evidence_ids": tuple(value["subject_evidence_ids"]),
                                   "object_evidence_ids": tuple(value["object_evidence_ids"])})


def validate_assertion_members(values, object_members):
    if len(values) > 1000 or len({value.assertion_id for value in values}) != len(values):
        raise ImageRevisionIntegrityError("invalid or oversized assertion membership")
    endpoints = {(value.subject_revision_id, value.predicate, value.object_revision_id) for value in values}
    if len(endpoints) != len(values):
        raise ImageRevisionIntegrityError("duplicate reference endpoints require review of the existing assertion")
    objects = {item["object_id"]: item for item in object_members}
    for value in values:
        for object_id, revision_id, evidence in (
                (value.subject_object_id, value.subject_revision_id, value.subject_evidence_ids),
                (value.object_id, value.object_revision_id, value.object_evidence_ids)):
            member = objects.get(object_id)
            if (member is None or member["kind"] != "source_document"
                    or member.get("document_revision_id") != revision_id
                    or not set(evidence).issubset(member["evidence_ids"])):
                raise ImageRevisionIntegrityError("assertion endpoint is outside frozen image membership")


def reviewed_membership_digest(objects, assertions):
    return snapshot_digest({"objects": objects, "assertions": assertions})


def build_reviewed_artifact(parent, parent_id, parent_hash, selected):
    require_digest(parent_hash)
    if not parent_id or not selected:
        raise ValueError("a reviewed candidate requires a parent and selected decisions")
    inherited = {item["assertion_id"]: assertion_member(item) for item in parent.get("assertion_members", [])}
    if len({item.assertion_id for item in selected}) != len(selected):
        raise ValueError("duplicate selected assertion")
    inherited.update({item.assertion_id: item for item in selected})
    members = tuple(inherited[key] for key in sorted(inherited))
    validate_assertion_members(members, parent["members"])
    from .semantic_membership import SEMANTIC_IMAGE_POLICY
    if len(members) + len(parent.get("semantic_assertion_members", [])) > 1000:
        raise ImageRevisionIntegrityError("combined assertion membership exceeds budget")
    return {**parent, "schema": SEMANTIC_IMAGE_POLICY if parent.get("schema") == SEMANTIC_IMAGE_POLICY else REVIEWED_IMAGE_POLICY, "parent_revision_id": parent_id,
            "parent_artifact_hash": parent_hash, "assertion_members": [asdict(item) for item in members]}
