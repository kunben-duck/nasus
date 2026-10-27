"""Frozen relation dependencies, never business approval or verified coverage."""
from __future__ import annotations

from dataclasses import dataclass

from .image_revision import ImageRevisionIntegrityError, require_digest
from .source_snapshots import snapshot_digest


RELATION_PROVENANCE_POLICY = "nasus.image-relation-provenance.v1"
RELATION_PROVENANCE_KINDS = frozenset({"object_pin", "reference_proposal", "reference_assertion",
    "reference_decision", "semantic_evaluation", "semantic_assertion", "semantic_decision",
    "relation_member", "image_relations"})


@dataclass(frozen=True)
class RelationProvenanceNode:
    project_id: str
    kind: str
    artifact_id: str
    artifact_hash: str
    metadata_hash: str
    parents: tuple[str, ...]
    object_node_key: str | None = None
    object_node_hash: str | None = None

    def __post_init__(self):
        if (self.kind not in RELATION_PROVENANCE_KINDS
                or any(type(v) is not str or not 1 <= len(v) <= 1100 for v in (self.project_id, self.artifact_id))):
            raise ImageRevisionIntegrityError("Invalid relation provenance identity.")
        require_digest(self.artifact_hash)
        require_digest(self.metadata_hash)
        if (type(self.parents) is not tuple or self.parents != tuple(sorted(set(self.parents)))
                or any(type(p) is not str or not 1 <= len(p) <= 1200 or not p.partition(":")[2]
                       or p == self.key for p in self.parents)):
            raise ImageRevisionIntegrityError("Invalid relation provenance parents.")
        allowed = {"object_pin": set(), "reference_proposal": {"object_pin"},
            "reference_assertion": {"object_pin", "reference_proposal"},
            "reference_decision": {"reference_assertion", "reference_decision"},
            "semantic_evaluation": {"object_pin"}, "semantic_assertion": {"object_pin", "semantic_evaluation"},
            "semantic_decision": {"semantic_assertion", "semantic_decision"},
            "relation_member": {"reference_decision", "semantic_decision"},
            "image_relations": {"object_pin", "relation_member"}}
        kinds = [p.partition(":")[0] for p in self.parents]
        required = {"reference_proposal": "object_pin", "reference_assertion": "reference_proposal",
            "reference_decision": "reference_assertion", "semantic_evaluation": "object_pin",
            "semantic_assertion": "semantic_evaluation", "semantic_decision": "semantic_assertion",
            "image_relations": "object_pin"}
        if (not set(kinds).issubset(allowed[self.kind])
                or self.kind in required and kinds.count(required[self.kind]) != 1
                or self.kind == "relation_member" and len(kinds) != 1
                or self.kind.endswith("_decision") and kinds.count(self.kind) > 1):
            raise ImageRevisionIntegrityError("Invalid relation provenance ancestry.")
        if self.kind == "object_pin":
            if (type(self.object_node_key) is not str or self.artifact_id != self.object_node_key
                    or self.object_node_key.partition(":")[0] not in {"image_objects", "member", "evidence"}
                    or not self.object_node_key.partition(":")[2] or self.artifact_hash != self.object_node_hash):
                raise ImageRevisionIntegrityError("Invalid native object provenance pin.")
            require_digest(self.object_node_hash)
        elif self.object_node_key is not None or self.object_node_hash is not None:
            raise ImageRevisionIntegrityError("Only an object pin can bridge native ancestry.")

    @property
    def key(self):
        return self.kind + ":" + self.artifact_id

    @property
    def content_hash(self):
        # Explicit v1 fields prevent future DTO extensions from rewriting history.
        return snapshot_digest({"policy_revision": RELATION_PROVENANCE_POLICY,
            **{key: getattr(self, key) for key in ("project_id", "kind", "artifact_id", "artifact_hash",
                "metadata_hash", "parents", "object_node_key", "object_node_hash")}})
