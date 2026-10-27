from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest


IMAGE_POLICY = "nasus.image-candidate.v1"


class ImageRevisionConflict(RuntimeError):
    pass


class ImageRevisionIntegrityError(RuntimeError):
    pass


class ImageArtifactUnavailable(RuntimeError):
    pass


class ImageRevisionPageTooLarge(ValueError):
    pass


def require_digest(value: str) -> None:
    if (not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in value[7:])):
        raise ImageRevisionIntegrityError("Expected a canonical SHA-256 digest.")


def require_frozen_inputs(manifest: CapturedSourceManifest) -> None:
    members = manifest.members
    if (not members or len({member.binding_id for member in members}) != len(members)
            or not any(member.source_type == "code" for member in members)
            or any(member.source_type == "code" and member.status != "captured" for member in members)):
        raise ImageRevisionConflict("A candidate requires captured revisions for every selected code source.")
    if any(member.source_type not in {"code", "us_doc", "test_asset"}
           or member.status not in {"captured", "failed", "pending", "legacy_unverified"}
           or (member.status == "captured" and not member.source_revision_id)
           or (member.status != "captured" and member.source_revision_id is not None) for member in members):
        raise ImageRevisionIntegrityError("Invalid frozen source status or revision.")
    if snapshot_digest([asdict(member) for member in sorted(members, key=lambda item: item.binding_id)]) != manifest.content_hash:
        raise ImageRevisionIntegrityError("Source manifest integrity verification failed.")


@dataclass(frozen=True)
class ImageObjectMember:
    object_id: str
    object_hash: str
    kind: str
    entity_id: Optional[str] = None
    entity_revision_id: Optional[str] = None
    source_revision_id: Optional[str] = None
    evidence_ids: tuple[str, ...] = ()
    document_revision_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.object_id or self.kind not in {"code_entity", "source_document", "legacy_observation"}:
            raise ValueError("invalid image object membership")
        pin = (self.entity_id, self.entity_revision_id, self.source_revision_id)
        if (self.kind == "code_entity" and not all(pin)) or (self.kind == "legacy_observation" and any(pin)):
            raise ValueError("code membership must pin the complete entity and source revision")
        if (self.kind == "source_document" and (self.entity_id or self.entity_revision_id or not self.source_revision_id
                or not self.document_revision_id)) or (self.kind != "source_document" and self.document_revision_id):
            raise ValueError("invalid source document membership")
        if (not isinstance(self.evidence_ids, tuple) or len(self.evidence_ids) > 100
                or len(set(self.evidence_ids)) != len(self.evidence_ids)
                or any(not isinstance(item, str) or not item for item in self.evidence_ids)
                or (self.kind == "legacy_observation" and self.evidence_ids)):
            raise ValueError("invalid frozen evidence membership")
        require_digest(self.object_hash)


def member_payload(member: ImageObjectMember) -> dict:
    value = asdict(member)
    # Preserve hashes of candidates frozen before document membership existed.
    if value["document_revision_id"] is None:
        del value["document_revision_id"]
    return value


@dataclass(frozen=True)
class ImageRevisionSummary:
    image_revision_id: str
    project_id: str
    baseline_id: str
    manifest_id: str
    manifest_hash: str
    artifact_hash: str
    membership_hash: str
    policy_version: str
    recorded_at: str
    object_count: int
    code_member_count: int
    relationship_count: int
    status: str = "candidate"
    publication: str = "blocked_pending_revision_governance"
    parent_revision_id: Optional[str] = None
    parent_artifact_hash: Optional[str] = None
    assertion_count: int = 0


def build_image_artifact(manifest: CapturedSourceManifest, baseline_id: str,
                         objects: list[dict], relationships: list[dict]) -> tuple[dict, tuple[ImageObjectMember, ...]]:
    require_frozen_inputs(manifest)
    if not baseline_id or not objects or len(objects) > 50000 or len(relationships) > 100000:
        raise ValueError("invalid or oversized image candidate")
    object_ids = {item["id"] for item in objects}
    if len(object_ids) != len(objects):
        raise ValueError("duplicate image object")
    if len({item["id"] for item in relationships}) != len(relationships) or any(
        item["project_id"] != manifest.project_id or item["baseline_id"] != baseline_id
        or item["from_object_id"] not in object_ids or item["to_object_id"] not in object_ids
        for item in relationships
    ):
        raise ImageRevisionIntegrityError("Image relationships are not closed over this candidate.")
    members = []
    revisions = {member.source_revision_id for member in manifest.members}
    # Freeze the compatibility projection without treating its inferred labels,
    # confidence or relationships as approved assertions or business oracles.
    frozen_objects = [{key: value for key, value in item.items() if key != "freshness"}
                      for item in sorted(objects, key=lambda item: item["id"])]
    for item in frozen_objects:
        reference = item.get("code_reference")
        document_reference = item.get("document_reference")
        if reference and document_reference:
            raise ImageRevisionIntegrityError("Object cannot be both code and source document.")
        reference = reference or document_reference
        if reference and reference["source_revision_id"] not in revisions:
            raise ImageRevisionConflict("Image object is outside the selected source manifest.")
        members.append(ImageObjectMember(item["id"], snapshot_digest(item),
            "source_document" if document_reference else "code_entity" if reference else "legacy_observation", **(reference or {})))
    payload = {
        "schema": IMAGE_POLICY, "project_id": manifest.project_id, "baseline_id": baseline_id,
        "manifest_id": manifest.manifest_id, "manifest_hash": manifest.content_hash,
        "source_members": [asdict(member) for member in manifest.members],
        "semantic_status": "legacy_observations_not_approved_assertions",
        "publication": "blocked_pending_revision_governance",
        "objects": frozen_objects, "relationships": sorted(relationships, key=lambda item: item["id"]),
        "members": [member_payload(member) for member in members],
    }
    return payload, tuple(members)


def verify_image_artifact(payload: dict, header: ImageRevisionSummary) -> None:
    """Verify the complete frozen membership, not merely the requested page."""
    try:
        manifest = CapturedSourceManifest(payload["manifest_id"], payload["project_id"], payload["manifest_hash"], "",
            tuple(SourceManifestMember(**item) for item in payload["source_members"]))
        rebuilt, members = build_image_artifact(manifest, payload["baseline_id"], payload["objects"], payload["relationships"])
        pinned = tuple(ImageObjectMember(**{**item, "evidence_ids": tuple(item["evidence_ids"])}) for item in payload["members"])
        if len(pinned) != len(members):
            raise ImageRevisionIntegrityError("Image member count mismatch.")
        for item, actual in zip(members, pinned):
            if {key: value for key, value in asdict(actual).items() if key != "evidence_ids"} != {
                key: value for key, value in asdict(item).items() if key != "evidence_ids"
            }:
                raise ImageRevisionIntegrityError("Image object does not match its frozen membership.")
        rebuilt["members"] = [member_payload(member) for member in pinned]
        membership_hash = snapshot_digest(rebuilt["members"])
        if header.policy_version != IMAGE_POLICY:
            from .image_membership import (REVIEWED_IMAGE_POLICY, assertion_member,
                validate_assertion_members, reviewed_membership_digest)
            from .semantic_membership import (SEMANTIC_IMAGE_POLICY, semantic_member,
                validate_semantic_members, semantic_membership_digest)
            if (header.policy_version not in {REVIEWED_IMAGE_POLICY, SEMANTIC_IMAGE_POLICY} or not header.parent_revision_id
                    or header.parent_revision_id == header.image_revision_id or not header.parent_artifact_hash):
                raise ImageRevisionIntegrityError("Invalid reviewed image parent.")
            require_digest(header.parent_artifact_hash)
            assertions = tuple(assertion_member(item) for item in payload["assertion_members"])
            validate_assertion_members(assertions, rebuilt["members"])
            if [item.assertion_id for item in assertions] != sorted(item.assertion_id for item in assertions):
                raise ImageRevisionIntegrityError("Invalid frozen assertion count or ordering.")
            rebuilt.update(schema=header.policy_version, parent_revision_id=header.parent_revision_id,
                parent_artifact_hash=header.parent_artifact_hash, assertion_members=[asdict(item) for item in assertions])
            membership_hash = reviewed_membership_digest(rebuilt["members"], rebuilt["assertion_members"])
            semantics = ()
            if header.policy_version == SEMANTIC_IMAGE_POLICY:
                semantics = tuple(semantic_member(item) for item in payload["semantic_assertion_members"])
                validate_semantic_members(semantics, rebuilt["members"], header.project_id)
                if [item.claim_id for item in semantics] != sorted(item.claim_id for item in semantics):
                    raise ImageRevisionIntegrityError("Invalid semantic membership ordering.")
                rebuilt["semantic_assertion_members"] = [asdict(item) for item in semantics]
                membership_hash = semantic_membership_digest(rebuilt["members"], rebuilt["assertion_members"], rebuilt["semantic_assertion_members"])
            if not 1 <= header.assertion_count <= 1000 or header.assertion_count != len(assertions) + len(semantics):
                raise ImageRevisionIntegrityError("Invalid combined assertion count.")
        elif header.parent_revision_id is not None or header.parent_artifact_hash is not None or header.assertion_count != 0:
            raise ImageRevisionIntegrityError("Legacy candidate cannot contain review membership.")
        if (snapshot_digest(rebuilt) != header.artifact_hash or snapshot_digest(payload) != header.artifact_hash
                or membership_hash != header.membership_hash
                or header.project_id != manifest.project_id or header.manifest_id != manifest.manifest_id
                or header.manifest_hash != manifest.content_hash or header.baseline_id != payload["baseline_id"]
                or header.status != "candidate"
                or header.object_count != len(members) or header.relationship_count != len(payload["relationships"])
                or header.code_member_count != sum(item.kind == "code_entity" for item in members)):
            raise ImageRevisionIntegrityError("Image artifact header or digest mismatch.")
    except (KeyError, TypeError, ValueError, ImageRevisionConflict) as exc:
        raise ImageRevisionIntegrityError("Malformed frozen image artifact.") from exc
