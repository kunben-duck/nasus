"""Metadata-only projection in the originating fact/Outbox transaction.

The v1 projector is also the migration backfill contract. It never grants
authority, reads private bodies, or calls another bounded context's repository.
"""
from sqlalchemy import insert, select

from ...domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationNode
from ...domain.system_image.derivation_registry import DerivationRegistration, FrozenQueryScope, REGISTRY_POLICY
from ...domain.system_image.source_snapshots import SourceManifestMember, snapshot_digest
from .context_pack_models import ContextPackRecord as Context
from .derivation_registry_models import (
    DerivationRegistryRecord as Node, DerivationRegistryEdgeRecord as Edge,
    ContextQueryScopeRecord as QueryScope, ContextQuerySourceRecord as QuerySource,
)
from .image_revision_models import ImageRevisionRecord as Image
from .source_snapshot_models import SourceManifestMemberRecord as Member, SourceManifestRecord as Manifest
from .test_design_scope_models import TestDesignScopeRecord as Scope
from .test_design_result_models import TestDesignResultRecord as Result, TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage
from .test_design_mapping_models import TestDesignMappingRecord as Mapping


FACT_EVENTS = {
    "system_image.context.compiled": "context",
    "quality.test_design_scope.reviewed": "scope",
    "quality.test_design.generated": "generation",
    "quality.test_design_mapping.reviewed": "mapping",
}


def _metadata(row, fields):
    if (row is None or type(row.payload) is not dict or snapshot_digest(row.payload) != row.content_hash
            or any(row.payload.get(key) != getattr(row, key) for key in fields)):
        raise DerivationImpactIntegrityError("derivation fact metadata mismatch")
    return row.payload


class DerivationRegistryProjector:
    def _node(self, session, registration):
        self._nodes(session, (registration,))

    def _nodes(self, session, registrations):
        if not registrations:
            return
        project_id, context_id = registrations[0].project_id, registrations[0].context_id
        keys = [item.node.key for item in registrations]
        if len(set(keys)) != len(keys) or any((item.project_id, item.context_id) != (project_id, context_id) for item in registrations):
            raise DerivationImpactIntegrityError("inconsistent derivation registration batch")
        existing = {row.node_key: row for row in session.scalars(select(Node).where(
            Node.project_id == project_id, Node.node_key.in_(keys)))}
        edges = {}
        for row in session.scalars(select(Edge).where(Edge.project_id == project_id, Edge.node_key.in_(keys)).order_by(Edge.parent_key)):
            edges.setdefault(row.node_key, []).append(row.parent_key)
        parents = {parent for item in registrations for parent in item.node.dependencies}
        ancestors = {row.node_key for row in session.scalars(select(Node).where(Node.project_id == project_id,
            Node.context_id == context_id, Node.node_key.in_(parents)))} if parents else set()
        if ancestors != parents:
            raise DerivationImpactIntegrityError("derivation ancestor registration missing")
        new_nodes, new_edges = [], []
        for registration in registrations:
            node = registration.node
            value = {"project_id": project_id, "context_id": context_id, "node_key": node.key,
                "kind": node.kind, "artifact_id": node.artifact_id, "artifact_hash": node.artifact_hash,
                "invocation_id": registration.invocation_id, "policy_revision": REGISTRY_POLICY,
                "content_hash": registration.content_hash}
            prior = existing.get(node.key)
            if prior is not None:
                if (any(getattr(prior, key) != item for key, item in value.items())
                        or tuple(edges.get(node.key, ())) != node.dependencies):
                    raise DerivationImpactIntegrityError("immutable derivation registration conflict")
            else:
                new_nodes.append(value)
                new_edges.extend({"project_id": project_id, "context_id": context_id,
                    "node_key": node.key, "parent_key": parent} for parent in node.dependencies)
        if new_nodes:
            session.execute(insert(Node), new_nodes)
        if new_edges:
            session.execute(insert(Edge), new_edges)

    def _query_scope(self, session, value):
        header = {key: getattr(value, key) for key in ("project_id", "context_id", "image_revision_id",
            "image_artifact_hash", "manifest_id", "manifest_hash", "input_digest")}
        header.update(query_scope_fingerprint=value.fingerprint, source_members_hash=value.source_members_hash,
            member_count=len(value.source_members), policy_revision=REGISTRY_POLICY)
        prior = session.get(QueryScope, (value.project_id, value.context_id))
        if prior is not None:
            sources = session.scalars(select(QuerySource).where(QuerySource.project_id == value.project_id,
                QuerySource.context_id == value.context_id).order_by(QuerySource.binding_id)).all()
            expected = value.source_members_v1
            actual = [{key: getattr(row, key) for key in expected[0]} for row in sources]
            if (any(getattr(prior, key) != item for key, item in header.items()) or actual != expected
                    or any(row.manifest_id != value.manifest_id for row in sources)):
                raise DerivationImpactIntegrityError("immutable context query scope conflict")
            return
        session.add(QueryScope(**header))
        session.flush()
        session.add_all([QuerySource(project_id=value.project_id, context_id=value.context_id,
            manifest_id=value.manifest_id, **member) for member in value.source_members_v1])
        session.flush()

    def context(self, session, row):
        metadata = _metadata(row, ("project_id", "context_id", "image_revision_id", "invocation_id"))
        image = session.get(Image, row.image_revision_id)
        if (image is None or image.project_id != row.project_id
                or image.artifact_hash != metadata.get("image_artifact_hash")):
            raise DerivationImpactIntegrityError("derivation image pin mismatch")
        manifest = session.get(Manifest, image.manifest_id)
        if manifest is None or manifest.project_id != row.project_id or manifest.content_hash != image.manifest_hash:
            raise DerivationImpactIntegrityError("derivation source manifest pin mismatch")
        members = tuple(SourceManifestMember(member.binding_id, member.source_type, member.source_revision_id, member.status)
            for member in session.scalars(select(Member).where(Member.project_id == row.project_id,
                Member.manifest_id == image.manifest_id).order_by(Member.binding_id)))
        value = FrozenQueryScope(row.project_id, row.context_id, image.image_revision_id, image.artifact_hash,
            manifest.manifest_id, manifest.content_hash, metadata.get("input_digest"), members)
        self._node(session, DerivationRegistration(row.project_id, row.context_id, row.invocation_id,
            DerivationNode("context", row.context_id, metadata.get("artifact_hash"), ())))
        self._query_scope(session, value)

    def scope(self, session, row):
        value = _metadata(row, ("project_id", "revision_id", "context_id", "invocation_id", "previous_revision_id", "sequence", "status"))
        root = session.get(Context, row.context_id)
        if root is None or root.project_id != row.project_id or root.payload.get("artifact_hash") != value.get("context_artifact_hash"):
            raise DerivationImpactIntegrityError("derivation context pin mismatch")
        parents = ["context:" + row.context_id]
        if row.previous_revision_id:
            parents.append("scope:" + row.previous_revision_id)
        self._node(session, DerivationRegistration(row.project_id, row.context_id, row.invocation_id,
            DerivationNode("scope", row.revision_id, value.get("artifact_hash"), tuple(sorted(parents)))))

    def generation(self, session, row):
        value = _metadata(row, ("project_id", "generation_id", "scope_revision_id", "invocation_id", "status", "artifact_hash"))
        scope = session.get(Scope, row.scope_revision_id)
        if scope is None or scope.project_id != row.project_id:
            raise DerivationImpactIntegrityError("derivation generation scope mismatch")
        context_id = scope.context_id
        self._node(session, DerivationRegistration(row.project_id, context_id, row.invocation_id,
            DerivationNode("generation", row.generation_id, row.artifact_hash, ("scope:" + row.scope_revision_id,))))
        count = 0
        # Streaming rows avoids a global graph/case truncation or one giant list.
        cases = session.scalars(select(Case).where(Case.project_id == row.project_id,
            Case.generation_id == row.generation_id).order_by(Case.case_id).execution_options(yield_per=256))
        for batch in cases.partitions(256):
            registrations = []
            for case in batch:
                _metadata(case, ("case_id",))
                registrations.append(DerivationRegistration(row.project_id, context_id, row.invocation_id,
                    DerivationNode("case", row.generation_id + "/" + case.case_id, case.content_hash,
                        ("generation:" + row.generation_id,))))
            self._nodes(session, registrations)
            count += len(batch)
        coverage = session.get(Coverage, row.generation_id)
        if (count != value.get("case_count") or coverage is None or coverage.project_id != row.project_id
                or snapshot_digest(coverage.payload) != coverage.content_hash):
            raise DerivationImpactIntegrityError("derivation generation is missing complete cases or coverage")
        self._node(session, DerivationRegistration(row.project_id, context_id, row.invocation_id,
            DerivationNode("coverage", row.generation_id, coverage.content_hash, ("generation:" + row.generation_id,))))

    def mapping(self, session, row):
        value = _metadata(row, ("project_id", "revision_id", "generation_id", "invocation_id", "previous_revision_id", "sequence", "status"))
        result = session.get(Result, row.generation_id)
        scope = session.get(Scope, result.scope_revision_id) if result is not None else None
        if (result is None or result.project_id != row.project_id or result.artifact_hash != value.get("generation_artifact_hash")
                or scope is None or scope.project_id != row.project_id):
            raise DerivationImpactIntegrityError("derivation mapping generation mismatch")
        parents = ["generation:" + row.generation_id]
        if row.previous_revision_id:
            parents.append("mapping:" + row.previous_revision_id)
        self._node(session, DerivationRegistration(row.project_id, scope.context_id, row.invocation_id,
            DerivationNode("mapping", row.revision_id, value.get("artifact_hash"), tuple(sorted(parents)))))

    def project_event(self, session, event):
        kind = FACT_EVENTS.get(event.event_type)
        if kind is None:
            return
        model = {"context": Context, "scope": Scope, "generation": Result, "mapping": Mapping}[kind]
        row = session.get(model, event.entity_id)
        if row is None or event.patch.get("project_id") != row.project_id:
            raise DerivationImpactIntegrityError("derivation event has no matching project fact")
        getattr(self, kind)(session, row)

    def backfill(self, session):
        for model, method, order in ((Context, self.context, (Context.project_id, Context.context_id)),
                (Scope, self.scope, (Scope.project_id, Scope.scope_id, Scope.sequence)),
                (Result, self.generation, (Result.project_id, Result.generation_id)),
                (Mapping, self.mapping, (Mapping.project_id, Mapping.generation_id, Mapping.sequence))):
            for row in session.scalars(select(model).order_by(*order).execution_options(yield_per=128)):
                method(session, row)
        session.flush()
