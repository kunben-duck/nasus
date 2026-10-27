"""Object-source subgraph; not semantic authority or execution provenance."""
from dataclasses import dataclass

from .image_revision import ImageRevisionIntegrityError, require_digest
from .source_snapshots import snapshot_digest


OBJECT_PROVENANCE_POLICY = "nasus.image-object-provenance.v1"
OBJECT_PROVENANCE_KINDS = frozenset({"source", "manifest", "code", "document", "evidence", "member", "image_objects"})


@dataclass(frozen=True)
class ObjectProvenanceNode:
    project_id: str
    kind: str
    artifact_id: str
    artifact_hash: str
    metadata_hash: str
    source_pins: tuple[tuple[str, str], ...]
    parents: tuple[str, ...]

    def __post_init__(self):
        if (self.kind not in OBJECT_PROVENANCE_KINDS
                or any(type(value) is not str or not 1 <= len(value) <= 1024
                       for value in (self.project_id, self.artifact_id))):
            raise ImageRevisionIntegrityError("Invalid object provenance identity.")
        require_digest(self.artifact_hash)
        require_digest(self.metadata_hash)
        if (type(self.source_pins) is not tuple
                or any(type(pin) is not tuple or len(pin) != 2
                       or any(type(v) is not str or not 1 <= len(v) <= 256 for v in pin) for pin in self.source_pins)
                or self.source_pins != tuple(sorted(set(self.source_pins)))
                or type(self.parents) is not tuple
                or any(type(p) is not str or not 1 <= len(p) <= 1100 for p in self.parents)
                or self.parents != tuple(sorted(set(self.parents)))):
            raise ImageRevisionIntegrityError("Invalid object provenance pins.")
        allowed = {"source": set(), "manifest": {"source"}, "code": {"source"},
            "document": {"source", "document"}, "evidence": {"source"},
            "member": {"code", "document", "evidence"}, "image_objects": {"manifest", "member"}}
        kinds = [parent.partition(":")[0] for parent in self.parents]
        if (any(not p.partition(":")[2] or p == self.key for p in self.parents)
                or not set(kinds).issubset(allowed[self.kind])
                or self.kind in {"code", "document", "evidence"} and kinds.count("source") != 1
                or self.kind == "document" and kinds.count("document") > 1
                or self.kind == "image_objects" and (kinds.count("manifest") != 1 or "member" not in kinds)
                or self.kind in {"source", "code", "document", "evidence"} and len(self.source_pins) != 1
                or self.kind == "member" and (len(self.source_pins) > 1
                    or kinds.count("code") + kinds.count("document") != len(self.source_pins))):
            raise ImageRevisionIntegrityError("Invalid object provenance ancestors.")
        source_keys = tuple(sorted({"source:" + revision for _, revision in self.source_pins}))
        if (self.kind == "source" and self.artifact_id != self.source_pins[0][1]
                or self.kind in {"code", "document", "evidence", "manifest"}
                and tuple(p for p in self.parents if p.startswith("source:")) != source_keys):
            raise ImageRevisionIntegrityError("Object provenance source ancestor does not match its pin.")

    @property
    def key(self):
        return self.kind + ":" + self.artifact_id

    @property
    def content_hash(self):
        # All v1 fields are immutable scalars/tuples; recursive copying adds no
        # isolation and must not let future fields change historical digests.
        return snapshot_digest({"policy_revision": OBJECT_PROVENANCE_POLICY,
            "project_id": self.project_id, "kind": self.kind, "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash, "metadata_hash": self.metadata_hash,
            "source_pins": self.source_pins, "parents": self.parents})
