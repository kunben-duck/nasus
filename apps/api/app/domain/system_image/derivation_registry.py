"""Immutable provenance registrations, independent of the bounded impact view."""
from dataclasses import dataclass

from .derivation_impact import DerivationImpactIntegrityError, DerivationNode
from .evidence import valid_digest
from .source_snapshots import SourceManifestMember, snapshot_digest


REGISTRY_POLICY = "nasus.derivation-registry.v1"


def _identifier(value):
    if type(value) is not str or not 1 <= len(value) <= 256:
        raise DerivationImpactIntegrityError("invalid derivation registration identity")


@dataclass(frozen=True)
class DerivationRegistration:
    project_id: str
    context_id: str
    invocation_id: str
    node: DerivationNode

    def __post_init__(self):
        for value in (self.project_id, self.context_id, self.invocation_id):
            _identifier(value)
        if not isinstance(self.node, DerivationNode):
            raise DerivationImpactIntegrityError("invalid derivation registration node")
        parent_kinds = sorted(parent.partition(":")[0] for parent in self.node.dependencies)
        allowed = {"context": [[]], "scope": [["context"], ["context", "scope"]],
            "generation": [["scope"]], "case": [["generation"]], "coverage": [["generation"]],
            "mapping": [["generation"], ["generation", "mapping"]]}
        if (parent_kinds not in allowed[self.node.kind] or self.node.key in self.node.dependencies
                or self.node.kind == "context" and self.node.artifact_id != self.context_id
                or self.node.kind == "scope" and "context:" + self.context_id not in self.node.dependencies):
            raise DerivationImpactIntegrityError("derivation registration has invalid ancestors")

    @property
    def content_hash(self):
        return snapshot_digest({"policy_revision": REGISTRY_POLICY, "project_id": self.project_id,
            "context_id": self.context_id, "invocation_id": self.invocation_id, "node": self.node.payload_v1})


@dataclass(frozen=True)
class FrozenQueryScope:
    project_id: str
    context_id: str
    image_revision_id: str
    image_artifact_hash: str
    manifest_id: str
    manifest_hash: str
    input_digest: str
    source_members: tuple[SourceManifestMember, ...]

    def __post_init__(self):
        for value in (self.project_id, self.context_id, self.image_revision_id, self.manifest_id):
            _identifier(value)
        if any(type(value) is not str or not valid_digest(value)
                for value in (self.image_artifact_hash, self.manifest_hash, self.input_digest)):
            raise DerivationImpactIntegrityError("invalid query scope digest")
        if (type(self.source_members) is not tuple or not self.source_members
                or any(not isinstance(member, SourceManifestMember) for member in self.source_members)):
            raise DerivationImpactIntegrityError("query scope requires complete source membership")
        keys = tuple(member.binding_id for member in self.source_members)
        if keys != tuple(sorted(set(keys))):
            raise DerivationImpactIntegrityError("query scope sources must be unique and ordered")
        for member in self.source_members:
            _identifier(member.binding_id)
            if (member.source_type not in {"code", "us_doc", "test_asset"}
                    or member.status not in {"captured", "failed", "pending", "legacy_unverified"}
                    or (member.status == "captured") != (member.source_revision_id is not None)):
                raise DerivationImpactIntegrityError("invalid query scope source state")
            if member.source_revision_id is not None:
                _identifier(member.source_revision_id)

    @property
    def source_members_hash(self):
        return snapshot_digest(self.source_members_v1)

    @property
    def source_members_v1(self):
        return [{"binding_id": member.binding_id, "source_type": member.source_type,
            "source_revision_id": member.source_revision_id, "status": member.status}
            for member in self.source_members]

    @property
    def fingerprint(self):
        # Same semantic input as the existing fixed-context impact contract.
        return snapshot_digest({"input_digest": self.input_digest,
            "image_artifact_hash": self.image_artifact_hash,
            "source_members": self.source_members_v1})
