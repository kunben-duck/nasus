"""Metadata-only immutable bridge; ACL and archived body verification stay outside."""
from sqlalchemy import select

from ...domain.system_image.context_pack import ContextPackIntegrityError
from ...domain.system_image.context_provenance import ContextProvenanceAnchor
from ...domain.system_image.derivation_impact import DerivationNode
from ...domain.system_image.derivation_registry import DerivationRegistration, FrozenQueryScope, REGISTRY_POLICY
from ...domain.system_image.object_provenance import ObjectProvenanceNode, OBJECT_PROVENANCE_POLICY
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import SourceManifestMember, snapshot_digest
from .context_pack_models import ContextPackRecord as Context
from .context_provenance_models import ContextProvenanceAnchorRecord as Anchor
from .derivation_registry_models import (
    DerivationRegistryRecord as Derivation, DerivationRegistryEdgeRecord as Dependency,
    ContextQueryScopeRecord as QueryScope, ContextQuerySourceRecord as QuerySource,
)
from .image_revision_models import ImageRevisionRecord as Image
from .object_provenance_models import (
    ImageObjectProvenanceRecord as Root, ObjectProvenanceNodeRecord as Node, ObjectProvenanceEdgeRecord as Edge,
)
from .source_snapshot_models import SourceManifestRecord as Manifest, SourceManifestMemberRecord as Member


def _require(condition):
    if not condition:
        raise ContextPackIntegrityError("context provenance anchor failed integrity verification")


class ContextProvenanceProjectorV1:
    def expected(self, session, context):
        try:
            return self._expected(session, context)
        except ContextPackIntegrityError:
            raise
        except (ValueError, TypeError, KeyError, ImageRevisionIntegrityError) as exc:
            raise ContextPackIntegrityError("context provenance anchor failed integrity verification") from exc

    def _expected(self, session, context):
        value = context.payload
        _require(type(value) is dict and snapshot_digest(value) == context.content_hash
            and all(value.get(k) == getattr(context, k)
                    for k in ("project_id", "context_id", "image_revision_id", "invocation_id")))
        project, ident = context.project_id, context.context_id
        derivation = session.get(Derivation, (project, "context:" + ident))
        _require(derivation is not None)
        registration = DerivationRegistration(project, ident, context.invocation_id,
            DerivationNode("context", ident, value.get("artifact_hash"), ()))
        _require(all(getattr(derivation, key) == expected for key, expected in {
            "context_id": ident, "kind": "context", "artifact_id": ident,
            "artifact_hash": value.get("artifact_hash"), "invocation_id": context.invocation_id,
            "policy_revision": REGISTRY_POLICY, "content_hash": registration.content_hash,
        }.items()) and session.scalar(select(Dependency.node_key).where(
            Dependency.project_id == project, Dependency.node_key == derivation.node_key).limit(1)) is None)
        image = session.get(Image, context.image_revision_id)
        _require(image is not None and image.project_id == project and image.artifact_hash == value.get("image_artifact_hash"))
        manifest = session.get(Manifest, image.manifest_id)
        _require(manifest is not None and manifest.project_id == project and manifest.content_hash == image.manifest_hash)
        members = tuple(SourceManifestMember(*row) for row in session.execute(select(
            Member.binding_id, Member.source_type, Member.source_revision_id, Member.status).where(
            Member.project_id == project, Member.manifest_id == image.manifest_id).order_by(Member.binding_id)))
        frozen = FrozenQueryScope(project, ident, image.image_revision_id, image.artifact_hash,
            manifest.manifest_id, manifest.content_hash, value.get("input_digest"), members)
        scope = session.get(QueryScope, (project, ident))
        _require(scope is not None and all(getattr(scope, key) == expected for key, expected in {
            "image_revision_id": image.image_revision_id, "image_artifact_hash": image.artifact_hash,
            "manifest_id": manifest.manifest_id, "manifest_hash": manifest.content_hash,
            "input_digest": frozen.input_digest, "query_scope_fingerprint": frozen.fingerprint,
            "source_members_hash": frozen.source_members_hash, "member_count": len(members),
            "policy_revision": REGISTRY_POLICY,
        }.items()))
        sources = [dict(row) for row in session.execute(select(QuerySource.binding_id, QuerySource.source_type,
            QuerySource.source_revision_id, QuerySource.status).where(QuerySource.project_id == project,
            QuerySource.context_id == ident).order_by(QuerySource.binding_id)).mappings()]
        _require(sources == frozen.source_members_v1 and session.scalar(select(QuerySource.binding_id).where(
            QuerySource.project_id == project, QuerySource.context_id == ident,
            QuerySource.manifest_id != manifest.manifest_id).limit(1)) is None)
        root = session.get(Root, (project, image.image_revision_id))
        _require(root is not None and root.node_key == "image_objects:" + image.image_revision_id)
        node = session.get(Node, (project, root.node_key))
        _require(node is not None and node.kind == "image_objects" and node.artifact_id == image.image_revision_id
            and node.artifact_hash == image.artifact_hash and node.policy_revision == OBJECT_PROVENANCE_POLICY)
        parents = session.execute(select(Edge.parent_key, Edge.node_hash, Edge.parent_hash).where(
            Edge.project_id == project, Edge.node_key == node.node_key).order_by(Edge.parent_key)).all()
        parent_keys = tuple(row.parent_key for row in parents)
        ancestry = ObjectProvenanceNode(project, "image_objects", image.image_revision_id,
            node.artifact_hash, node.metadata_hash, tuple(tuple(pin) for pin in node.source_pins), parent_keys)
        _require(ancestry.content_hash == root.content_hash == node.content_hash
            and ancestry.source_pins == tuple(sorted((m.binding_id, m.source_revision_id)
                for m in members if m.status == "captured"))
            and "manifest:" + manifest.manifest_id in parent_keys
            and all(row.node_hash == node.content_hash for row in parents))
        # Full native ancestry and raw bytes are still audited by image/evidence
        # application reads; this bridge cannot substitute for those checks.
        return ContextProvenanceAnchor(project, ident, registration.content_hash,
            image.image_revision_id, image.artifact_hash, ancestry.content_hash,
            manifest.manifest_id, manifest.content_hash, frozen.input_digest, frozen.fingerprint)

    def record(self, session, context):
        expected = self.expected(session, context).record_v1
        prior = session.get(Anchor, (context.project_id, context.context_id))
        if prior is not None:
            _require(all(getattr(prior, key) == value for key, value in expected.items()))
            return 0
        session.add(Anchor(**expected))
        session.flush()
        return 1

    def verify(self, session, context):
        expected = self.expected(session, context).record_v1
        prior = session.get(Anchor, (context.project_id, context.context_id))
        _require(prior is not None and all(getattr(prior, key) == value for key, value in expected.items()))
        return expected

    def project_event(self, session, event):
        if event.event_type != "system_image.context.compiled":
            return
        context = session.get(Context, event.entity_id)
        _require(context is not None and event.patch.get("project_id") == context.project_id
            and event.patch.get("image_revision_id") == context.image_revision_id
            and event.patch.get("context_id") == context.context_id)
        self.record(session, context)

    def backfill(self, session):
        from .object_provenance_projection_v1 import ObjectProvenanceProjectorV1
        count, previous = 0, None
        for context in session.scalars(select(Context).order_by(Context.project_id, Context.image_revision_id,
                Context.context_id).execution_options(yield_per=128)):
            image_key = (context.project_id, context.image_revision_id)
            if image_key != previous:
                image = session.get(Image, context.image_revision_id)
                _require(image is not None and image.project_id == context.project_id)
                ObjectProvenanceProjectorV1().image(session, image, write=False)
                previous = image_key
            count += self.record(session, context)
        session.flush()
        return count
