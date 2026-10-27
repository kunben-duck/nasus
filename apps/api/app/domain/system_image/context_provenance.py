"""Versioned bridge between object ancestry and the existing derivation graph."""
from dataclasses import dataclass

from .context_pack import ContextPackIntegrityError
from .evidence import valid_digest
from .source_snapshots import snapshot_digest


CONTEXT_PROVENANCE_POLICY = "nasus.context-provenance-anchor.v1"
ANCHOR_FIELDS = (
    "project_id", "context_id", "context_registration_hash", "image_revision_id",
    "image_artifact_hash", "image_provenance_hash", "manifest_id", "manifest_hash",
    "input_digest", "query_scope_fingerprint",
)


@dataclass(frozen=True)
class ContextProvenanceAnchor:
    project_id: str
    context_id: str
    context_registration_hash: str
    image_revision_id: str
    image_artifact_hash: str
    image_provenance_hash: str
    manifest_id: str
    manifest_hash: str
    input_digest: str
    query_scope_fingerprint: str

    def __post_init__(self):
        for field in ("project_id", "context_id", "image_revision_id", "manifest_id"):
            value = getattr(self, field)
            if type(value) is not str or not 1 <= len(value) <= 256:
                raise ContextPackIntegrityError("invalid context provenance identity")
        for field in set(ANCHOR_FIELDS) - {"project_id", "context_id", "image_revision_id", "manifest_id"}:
            value = getattr(self, field)
            if type(value) is not str or not valid_digest(value):
                raise ContextPackIntegrityError("invalid context provenance digest")

    @property
    def payload_v1(self):
        return {field: getattr(self, field) for field in ANCHOR_FIELDS}

    @property
    def content_hash(self):
        return snapshot_digest({"policy_revision": CONTEXT_PROVENANCE_POLICY, **self.payload_v1})

    @property
    def record_v1(self):
        return {**self.payload_v1, "context_node_key": "context:" + self.context_id,
            "image_node_key": "image_objects:" + self.image_revision_id,
            "policy_revision": CONTEXT_PROVENANCE_POLICY, "content_hash": self.content_hash}
