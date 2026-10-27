"""Compare frozen membership, never infer deletion, rename lineage or coverage."""
from dataclasses import asdict, dataclass
from typing import Optional

from .image_revision import ImageRevisionIntegrityError, verify_image_artifact
from .source_snapshots import snapshot_digest


CODE_MEMBER_DELTA_POLICY = "nasus.code-member-delta.v1"
CODE_MEMBER_DELTA_KINDS = frozenset({"added_member", "removed_member", "revision_changed", "projection_changed", "unchanged"})


@dataclass(frozen=True)
class CodeMemberPin:
    object_id: str
    entity_revision_id: str
    source_revision_id: str
    object_hash: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CodeMemberChange:
    binding_id: str
    entity_id: str
    kind: str
    before: Optional[CodeMemberPin]
    after: Optional[CodeMemberPin]


@dataclass(frozen=True)
class CodeMemberDelta:
    project_id: str
    before_image_revision_id: str
    before_image_hash: str
    after_image_revision_id: str
    after_image_hash: str
    changes: tuple[CodeMemberChange, ...]
    counts: dict[str, int]
    source_scope_changed: bool
    content_hash: str
    schema: str = CODE_MEMBER_DELTA_POLICY
    comparison_scope: str = "registered_members_of_two_frozen_images"
    source_deletions_verified: bool = False
    rename_lineage_transferred: bool = False
    impact_complete: bool = False
    approval_transferred: bool = False
    execution_authorized: bool = False


def _members(payload):
    sources = {item["source_revision_id"]: item["binding_id"] for item in payload["source_members"]
               if item["source_type"] == "code" and item["status"] == "captured"}
    result = {}
    for member in payload["members"]:
        if member["kind"] != "code_entity":
            continue
        binding = sources.get(member["source_revision_id"])
        key = (binding, member["entity_id"])
        if binding is None or key in result:
            raise ImageRevisionIntegrityError("Code delta requires one exact member per registered identity.")
        result[key] = CodeMemberPin(member["object_id"], member["entity_revision_id"], member["source_revision_id"],
            member["object_hash"], tuple(member["evidence_ids"]))
    return result, frozenset(sources.values())


def compare_code_members(before_header, before_payload, after_header, after_payload):
    if before_header.project_id != after_header.project_id:
        raise ValueError("Code delta requires images in one project.")
    verify_image_artifact(before_payload, before_header)
    verify_image_artifact(after_payload, after_header)
    if before_header.image_revision_id == after_header.image_revision_id and before_header != after_header:
        raise ImageRevisionIntegrityError("One image revision must identify one immutable header.")
    before, left_scope = _members(before_payload)
    after, right_scope = _members(after_payload)
    identities = {}
    revisions = {}
    for (binding, entity), pin in (*before.items(), *after.items()):
        if identities.setdefault(entity, binding) != binding:
            raise ImageRevisionIntegrityError("Registered identity changed its source binding.")
        revision_scope = (binding, entity, pin.source_revision_id)
        if revisions.setdefault(pin.entity_revision_id, revision_scope) != revision_scope:
            raise ImageRevisionIntegrityError("Registered revision changed its immutable scope.")
    changes = []
    for binding, entity in sorted(before.keys() | after.keys()):
        old, new = before.get((binding, entity)), after.get((binding, entity))
        kind = ("added_member" if old is None else "removed_member" if new is None else
                "revision_changed" if old.entity_revision_id != new.entity_revision_id else
                "projection_changed" if old != new else "unchanged")
        changes.append(CodeMemberChange(binding, entity, kind, old, new))
    counts = {kind: sum(item.kind == kind for item in changes) for kind in sorted(CODE_MEMBER_DELTA_KINDS)}
    value = dict(project_id=before_header.project_id, before_image_revision_id=before_header.image_revision_id,
        before_image_hash=before_header.artifact_hash, after_image_revision_id=after_header.image_revision_id,
        after_image_hash=after_header.artifact_hash, changes=tuple(changes), counts=counts,
        source_scope_changed=left_scope != right_scope)
    provisional = CodeMemberDelta(**value, content_hash="")
    payload = asdict(provisional)
    del payload["content_hash"]
    return CodeMemberDelta(**value, content_hash=snapshot_digest(payload))
