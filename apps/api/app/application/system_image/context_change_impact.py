from dataclasses import asdict, dataclass
import json
from typing import Protocol

from ...domain.system_image.derivation_impact import (
    DerivationImpact, DerivationImpactIntegrityError, DerivationImpactTooLarge, DerivationNode, assess_derivation_impact,
)
from ...domain.system_image.source_delta import SourceRevisionPin
from ...domain.system_image.source_snapshots import snapshot_digest


class ContextDependencyReadPort(Protocol):
    def read(self, project_id, context_id, *, pinned=None): ...


@dataclass(frozen=True)
class ContextChangeImpact:
    project_id: str
    context_id: str
    context_artifact_hash: str
    image_revision_id: str
    image_artifact_hash: str
    before: SourceRevisionPin
    after: SourceRevisionPin
    delta_hash: str
    dependencies: tuple[DerivationNode, ...]
    assessment: DerivationImpact
    prospective_only: bool = True
    new_dependencies_after_observation_included: bool = False


class ContextChangeImpactApplicationService:
    def __init__(self, contexts, images, deltas, quality: ContextDependencyReadPort, authorization):
        self.contexts, self.images, self.deltas = contexts, images, deltas
        self.quality, self.authorization = quality, authorization

    def read(self, project_id, context_id, context_artifact_hash, before_revision_id, after_revision_id, *, pinned=None):
        access = self.authorization.scope(project_id)
        context = self.contexts.read(project_id, context_id)
        self.authorization.require_current(access)
        metadata = context["metadata"]
        if metadata["artifact_hash"] != context_artifact_hash:
            raise DerivationImpactIntegrityError("context dependency root digest mismatch")
        header, image = self.images.frozen_snapshot(project_id, metadata["image_revision_id"])
        self.authorization.require_current(access)
        if header.artifact_hash != metadata["image_artifact_hash"]:
            raise DerivationImpactIntegrityError("context dependency image pin mismatch")
        self.authorization.require_current(access)
        delta = self.deltas.compare(project_id, before_revision_id, after_revision_id)
        self.authorization.require_current(access)
        member = next((item for item in image["source_members"] if item["binding_id"] == delta.before.binding_id), None)
        if member is None or member["source_revision_id"] != before_revision_id or member["status"] != "captured":
            raise DerivationImpactIntegrityError("source delta must start at this context's frozen source revision")
        try:
            nodes = self.quality.read(project_id, context_id, pinned=pinned)
        except Exception:
            self.authorization.require_current(access)
            raise
        self.authorization.require_current(access)
        root = DerivationNode("context", context_id, context_artifact_hash, ())
        nodes = tuple(sorted((root, *nodes), key=lambda node: node.key))
        fingerprint = snapshot_digest({"input_digest": metadata["input_digest"],
            "image_artifact_hash": header.artifact_hash, "source_members": image["source_members"]})
        assessment = assess_derivation_impact(nodes, root.key, delta, fingerprint)
        value = ContextChangeImpact(project_id, context_id, context_artifact_hash,
            header.image_revision_id, header.artifact_hash, delta.before, delta.after, delta.content_hash, nodes, assessment)
        self.authorization.require_current(access)
        if len(json.dumps(asdict(value), ensure_ascii=False).encode("utf-8")) > 65536:
            raise DerivationImpactTooLarge("context impact exceeds 64 KiB; no partial result is returned")
        self.authorization.require_current(access)
        return value
