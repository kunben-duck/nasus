from __future__ import annotations

from dataclasses import asdict, dataclass

from .image_revision import ImageRevisionIntegrityError, require_digest
from .semantic_review import SemanticAssertion, SemanticDecision, stored_semantic_assertion
from .source_snapshots import snapshot_digest


SEMANTIC_IMAGE_POLICY = "nasus.image-candidate.v3"
FREEZE_SEMANTIC_TOOL = "system_image.revisions.freeze_semantic"


@dataclass(frozen=True)
class ImageSemanticMember:
    assertion: SemanticAssertion
    decision: SemanticDecision

    def __post_init__(self):
        a, d = self.assertion, self.decision
        if (any(getattr(a, key) != getattr(d, key) for key in (
                "project_id", "image_revision_id", "evaluation_id", "evidence_digest", "claim_id", "assertion_id"))
                or a.digest != d.assertion_digest):
            raise ImageRevisionIntegrityError("semantic member decision does not pin its assertion")
        a.require_decision(d.decision)

    @property
    def claim_id(self):
        return self.assertion.claim_id


def semantic_member(value):
    if set(value) != {"assertion", "decision"}:
        raise ImageRevisionIntegrityError("unexpected semantic member fields")
    return ImageSemanticMember(stored_semantic_assertion(value["assertion"]), SemanticDecision(**value["decision"]))


def validate_semantic_members(values, objects, project_id):
    if not 1 <= len(values) <= 1000 or len({v.claim_id for v in values}) != len(values):
        raise ImageRevisionIntegrityError("invalid semantic membership size or duplicate claim")
    endpoints = set()
    objects = {v["object_id"]: v for v in objects}
    for value in values:
        a = value.assertion
        key = (a.subject_object_id, a.subject_revision_id, a.predicate, a.object_id, a.object_revision_id)
        if a.project_id != project_id or key in endpoints:
            raise ImageRevisionIntegrityError("semantic member scope or endpoint collision")
        endpoints.add(key)
        for object_id, revision, evidence, kind in (
                (a.subject_object_id, a.subject_revision_id, a.subject_evidence_ids,
                 "code_entity" if a.predicate == "implements" else "source_document"),
                (a.object_id, a.object_revision_id, a.object_evidence_ids, "source_document")):
            member = objects.get(object_id)
            if (member is None or member["kind"] != kind
                    or member.get("entity_revision_id" if kind == "code_entity" else "document_revision_id") != revision
                    or not set(evidence).issubset(member["evidence_ids"])):
                raise ImageRevisionIntegrityError("semantic endpoint is outside frozen membership")


def semantic_membership_digest(objects, references, semantics):
    return snapshot_digest({"objects": objects, "assertions": references, "semantic_assertions": semantics})


def build_semantic_artifact(parent, parent_id, parent_hash, selected):
    require_digest(parent_hash)
    if not parent_id or not selected or len({item.claim_id for item in selected}) != len(selected):
        raise ValueError("semantic freeze requires a parent and distinct reviewed claims")
    inherited = {item.claim_id: item for item in map(semantic_member, parent.get("semantic_assertion_members", []))}
    inherited.update({item.claim_id: item for item in selected})
    members = tuple(inherited[key] for key in sorted(inherited))
    validate_semantic_members(members, parent["members"], parent["project_id"])
    references = parent.get("assertion_members", [])
    if len(references) + len(members) > 1000:
        raise ImageRevisionIntegrityError("combined assertion membership exceeds budget")
    return {**parent, "schema": SEMANTIC_IMAGE_POLICY, "parent_revision_id": parent_id,
            "parent_artifact_hash": parent_hash, "assertion_members": references,
            "semantic_assertion_members": [asdict(item) for item in members]}
