"""Frozen migration contract for the complete object-source subgraph.

Uses the caller's Session. No private-body reads, independent transaction,
authority grant, semantic claim or mutable-head substitution belongs here.
"""
from sqlalchemy import insert, select

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageObjectMember, member_payload, require_digest
from ...domain.system_image.object_provenance import OBJECT_PROVENANCE_POLICY, ObjectProvenanceNode
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_entity_models import CodeEntityIdentityRecord as CodeIdentity, CodeEntityRevisionRecord as Code
from .document_projection_models import (
    SourceDocumentIdentityRecord as DocumentIdentity, SourceDocumentRevisionRecord as Document,
    SourceDocumentEvidenceRecord as DocumentEvidence,
)
from .image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from .source_evidence_models import SourceEvidenceRecord as Evidence, CodeEntityEvidenceRecord as CodeEvidence
from .source_snapshot_models import (
    SourceBindingRecord as Binding, SourceRevisionRecord as Source,
    SourceManifestRecord as Manifest, SourceManifestMemberRecord as ManifestMember,
)
from .object_provenance_models import (
    ObjectProvenanceNodeRecord as Node, ObjectProvenanceEdgeRecord as Edge, ImageObjectProvenanceRecord as Root,
)


def _fail():
    raise ImageRevisionIntegrityError("Image object provenance integrity verification failed.")


def _batches(values):
    values = list(values)
    for offset in range(0, len(values), 256):
        yield values[offset:offset + 256]


def _columns(model):
    # ORM column expressions retain autoflush, without populating identities.
    if model is Binding:
        # Frozen 0070 provenance needs no fields introduced by later migrations.
        return select(Binding.binding_id, Binding.project_id, Binding.kind)
    return select(*(getattr(model, column.name) for column in model.__table__.columns))


def _rows(session, model, column, values, project_id):
    rows = {}
    for batch in _batches(sorted(set(values))):
        for row in session.execute(_columns(model).where(model.project_id == project_id, column.in_(batch))):
            rows[getattr(row, column.key)] = row
    if len(rows) != len(set(values)):
        _fail()
    return rows


def _evidence_identity_hash_v1(item):
    # Keep the historical digest independent of future ORM columns.
    fields = ("project_id", "binding_id", "source_revision_id", "relative_path",
        "start_line", "end_line", "precision", "file_hash", "snippet_hash",
        "object_ref", "decoder_version", "extractor_version")
    return snapshot_digest({field: getattr(item, field) for field in fields})


class ObjectProvenanceProjectorV1:
    def expected(self, session, image, members=None):
        if image is None:
            _fail()
        project = image.project_id
        members = (session.execute(_columns(Member).where(Member.project_id == project,
            Member.image_revision_id == image.image_revision_id).order_by(Member.object_id)).all()
            if members is None else members)
        if (len(members) != image.object_count or not members
                or sum(m.kind == "code_entity" for m in members) != image.code_member_count
                or len({m.object_id for m in members}) != len(members)
                or any(m.project_id != project or m.image_revision_id != image.image_revision_id
                       or m.manifest_id != image.manifest_id for m in members)):
            _fail()
        for member in members:
            if (type(member.evidence_ids) is not list
                    or any(type(eid) is not str or not eid for eid in member.evidence_ids)
                    or len(set(member.evidence_ids)) != len(member.evidence_ids)
                    or member.kind not in {"code_entity", "source_document", "legacy_observation"}):
                _fail()
        manifest = session.execute(_columns(Manifest).where(Manifest.manifest_id == image.manifest_id)).one_or_none()
        manifest_members = session.execute(_columns(ManifestMember).where(ManifestMember.project_id == project,
            ManifestMember.manifest_id == image.manifest_id).order_by(ManifestMember.binding_id)).all()
        manifest_values = [{key: getattr(row, key) for key in
            ("binding_id", "source_type", "source_revision_id", "status")} for row in manifest_members]
        if (manifest is None or manifest.project_id != project or manifest.content_hash != image.manifest_hash
                or not manifest_members or snapshot_digest(manifest_values) != manifest.content_hash):
            _fail()
        bindings = _rows(session, Binding, Binding.binding_id, [m.binding_id for m in manifest_members], project)
        sources = _rows(session, Source, Source.source_revision_id,
            [m.source_revision_id for m in manifest_members if m.source_revision_id], project)
        nodes = {}

        def add(kind, ident, digest, metadata, pins, parents):
            node = ObjectProvenanceNode(project, kind, ident, digest, snapshot_digest(metadata),
                tuple(sorted(set(pins))), tuple(sorted(set(parents))))
            if node.key in nodes and nodes[node.key] != node:
                _fail()
            nodes[node.key] = node
            return node.key

        captured = {}
        for member in manifest_members:
            if (bindings[member.binding_id].kind != member.source_type
                    or member.source_type not in {"code", "us_doc", "test_asset"}
                    or member.status not in {"captured", "failed", "pending", "legacy_unverified"}
                    or (member.status == "captured") != (member.source_revision_id is not None)):
                _fail()
            if member.source_revision_id:
                source = sources[member.source_revision_id]
                if source.binding_id != member.binding_id or source.file_count <= 0 or source.byte_count < 0:
                    _fail()
                require_digest(source.manifest_hash)
                pin = (source.binding_id, source.source_revision_id)
                captured[pin] = member.source_type
                add("source", source.source_revision_id, source.content_hash,
                    {key: getattr(source, key) for key in ("binding_id", "source_revision_id", "content_hash",
                        "manifest_hash", "policy_version", "file_count", "byte_count")}, (pin,), ())
        manifest_key = add("manifest", manifest.manifest_id, manifest.content_hash, manifest_values,
            captured, ["source:" + revision for _, revision in captured])

        codes = _rows(session, Code, Code.entity_revision_id,
            [m.entity_revision_id for m in members if m.kind == "code_entity"], project)
        code_identities = _rows(session, CodeIdentity, CodeIdentity.entity_id, [c.entity_id for c in codes.values()], project)
        documents = _rows(session, Document, Document.document_revision_id,
            [m.document_revision_id for m in members if m.kind == "source_document"], project)
        parents = _rows(session, Document, Document.document_revision_id,
            [d.parent_document_revision_id for d in documents.values() if d.parent_document_revision_id], project)
        documents.update(parents)
        document_identities = _rows(session, DocumentIdentity, DocumentIdentity.entity_id,
            [d.entity_id for d in documents.values()], project)
        evidence = _rows(session, Evidence, Evidence.evidence_id, [eid for m in members for eid in m.evidence_ids], project)
        associations = {"code_entity": set(), "source_document": set()}
        for model, key, kind in ((CodeEvidence, CodeEvidence.entity_revision_id, "code_entity"),
                                (DocumentEvidence, DocumentEvidence.document_revision_id, "source_document")):
            ids = codes if kind == "code_entity" else documents
            for batch in _batches(ids):
                for row in session.execute(select(key, model.evidence_id, model.binding_id, model.source_revision_id).where(
                        model.project_id == project, key.in_(batch))):
                    associations[kind].add((getattr(row, key.key), row.evidence_id, row.binding_id, row.source_revision_id))

        for code in codes.values():
            identity = code_identities[code.entity_id]
            pin = (code.binding_id, code.source_revision_id)
            if (captured.get(pin) != "code" or identity.binding_id != code.binding_id
                    or type(code.payload) is not dict or type(identity.symbol_key) is not dict
                    or snapshot_digest(code.payload) != code.payload_hash
                    or snapshot_digest(identity.symbol_key) != identity.symbol_key_hash
                    or snapshot_digest(code.payload.get("symbol")) != identity.symbol_key_hash):
                _fail()
            add("code", code.entity_revision_id, code.payload_hash,
                {"entity_id": code.entity_id, "symbol_key_hash": identity.symbol_key_hash,
                 "binding_id": code.binding_id, "source_revision_id": code.source_revision_id},
                (pin,), ("source:" + code.source_revision_id,))
        # Source components have exactly one non-component requirement parent.
        ordered_documents = sorted(documents.values(), key=lambda d: bool(d.parent_document_revision_id))
        for doc in ordered_documents:
            identity = document_identities[doc.entity_id]
            pin = (doc.binding_id, doc.source_revision_id)
            dependencies = ["source:" + doc.source_revision_id]
            if (pin not in captured or identity.binding_id != doc.binding_id
                    or type(identity.identity_key) is not dict
                    or snapshot_digest(identity.identity_key) != identity.identity_hash):
                _fail()
            if doc.parent_document_revision_id:
                parent = documents.get(doc.parent_document_revision_id)
                if (parent is None or (parent.binding_id, parent.source_revision_id) != pin
                        or parent.kind != "requirement" or parent.parent_document_revision_id
                        or doc.kind not in {"acceptance_criterion", "business_rule"}):
                    _fail()
                dependencies.append("document:" + parent.document_revision_id)
            elif doc.kind in {"acceptance_criterion", "business_rule"}:
                _fail()
            add("document", doc.document_revision_id, doc.payload_hash,
                {"entity_id": doc.entity_id, "identity_hash": identity.identity_hash,
                 "binding_id": doc.binding_id, "source_revision_id": doc.source_revision_id,
                 "kind": doc.kind, "parent_document_revision_id": doc.parent_document_revision_id}, (pin,), dependencies)

        for item in evidence.values():
            pin = (item.binding_id, item.source_revision_id)
            # Audit private locator fields without copying them into the graph.
            if (pin not in captured or _evidence_identity_hash_v1(item) != item.identity_hash
                    or item.start_line < 1 or item.end_line < item.start_line
                    or item.precision not in {"exact", "approximate"}
                    or (item.precision == "exact") != (item.snippet_hash is not None)):
                _fail()
            require_digest(item.file_hash)
            if item.snippet_hash is not None:
                require_digest(item.snippet_hash)
            add("evidence", item.evidence_id, item.identity_hash,
                {key: getattr(item, key) for key in ("binding_id", "source_revision_id", "file_hash", "snippet_hash",
                    "precision", "decoder_version", "extractor_version")}, (pin,), ("source:" + item.source_revision_id,))

        member_values, member_keys = [], []
        for member in members:
            try:
                value = member_payload(ImageObjectMember(member.object_id, member.object_hash, member.kind, member.entity_id,
                    member.entity_revision_id, member.source_revision_id, tuple(member.evidence_ids), member.document_revision_id))
            except (ValueError, TypeError):
                _fail()
            member_values.append(value)
            dependencies, pins = [], ()
            if member.kind != "legacy_observation":
                pin = (member.binding_id, member.source_revision_id)
                entity = codes.get(member.entity_revision_id) if member.kind == "code_entity" else documents.get(member.document_revision_id)
                if (pin not in captured or entity is None or (entity.binding_id, entity.source_revision_id) != pin
                        or member.kind == "code_entity" and entity.entity_id != member.entity_id):
                    _fail()
                revision = member.entity_revision_id if member.kind == "code_entity" else member.document_revision_id
                dependencies.append(("code:" if member.kind == "code_entity" else "document:") + revision)
                for eid in member.evidence_ids:
                    if (revision, eid, member.binding_id, member.source_revision_id) not in associations[member.kind]:
                        _fail()
                    if (evidence[eid].binding_id, evidence[eid].source_revision_id) != pin:
                        _fail()
                    dependencies.append("evidence:" + eid)
                pins = (pin,)
            elif member.binding_id is not None:
                _fail()
            member_keys.append(add("member", image.image_revision_id + "/" + member.object_id, member.object_hash,
                value, pins, dependencies))
        add("image_objects", image.image_revision_id, image.artifact_hash,
            {"manifest_id": image.manifest_id, "manifest_hash": image.manifest_hash,
             "membership_hash": image.membership_hash, "policy_version": image.policy_version,
             "object_count": image.object_count, "code_member_count": image.code_member_count,
             "object_members_hash": snapshot_digest(member_values)}, captured, (manifest_key, *member_keys))
        if any(parent not in nodes for node in nodes.values() for parent in node.parents):
            _fail()
        return nodes

    @staticmethod
    def _values(node, content_hash):
        return {"project_id": node.project_id, "node_key": node.key, "kind": node.kind,
            "artifact_id": node.artifact_id, "artifact_hash": node.artifact_hash, "metadata_hash": node.metadata_hash,
            "source_pins": [list(pin) for pin in node.source_pins], "content_hash": content_hash,
            "policy_revision": OBJECT_PROVENANCE_POLICY}

    def _compare(self, session, nodes, *, write):
        project = next(iter(nodes.values())).project_id
        # A root can have thousands of parents. Hash it once, not once per edge.
        hashes = {key: node.content_hash for key, node in nodes.items()}
        existing, edges = {}, {}
        # Compare column values directly without allocating ORM identities for
        # every immutable node and edge on each paginated read.
        node_columns = [getattr(Node, column.name) for column in Node.__table__.columns]
        for batch in _batches(nodes):
            existing.update({row["node_key"]: row for row in session.execute(select(*node_columns).where(
                Node.project_id == project, Node.node_key.in_(batch))).mappings()})
            for row in session.execute(select(Edge.node_key, Edge.parent_key, Edge.node_hash, Edge.parent_hash).where(
                    Edge.project_id == project, Edge.node_key.in_(batch))).mappings():
                edges.setdefault(row["node_key"], {})[row["parent_key"]] = (row["node_hash"], row["parent_hash"])
        missing = []
        for key, node in nodes.items():
            row = existing.get(key)
            if row is None:
                if not write or key in edges:
                    _fail()
                missing.append(self._values(node, hashes[key]))
                continue
            if (any(row[field] != value for field, value in self._values(node, hashes[key]).items())
                    or edges.get(key, {}) != {p: (hashes[key], hashes[p]) for p in node.parents}):
                _fail()
        for batch in _batches(missing):
            session.execute(insert(Node), batch)
        new_edges = ({"project_id": project, "node_key": value["node_key"], "parent_key": parent,
            "node_hash": hashes[value["node_key"]], "parent_hash": hashes[parent]}
            for value in missing for parent in nodes[value["node_key"]].parents)
        batch = []
        for edge in new_edges:
            batch.append(edge)
            if len(batch) == 256:
                session.execute(insert(Edge), batch)
                batch = []
        if batch:
            session.execute(insert(Edge), batch)
        return len(missing)

    def image(self, session, image, *, write, members=None):
        nodes = self.expected(session, image, members)
        count = self._compare(session, nodes, write=write)
        root_node = nodes["image_objects:" + image.image_revision_id]
        expected = {"project_id": image.project_id, "image_revision_id": image.image_revision_id,
            "node_key": root_node.key, "content_hash": root_node.content_hash}
        root = session.get(Root, (image.project_id, image.image_revision_id))
        if root is None:
            if not write:
                _fail()
            session.add(Root(**expected))
            session.flush()
        elif any(getattr(root, key) != value for key, value in expected.items()):
            _fail()
        return count

    def project_event(self, session, event):
        if event.event_type != "system_image.candidate.frozen":
            return
        image = session.get(Image, event.entity_id)
        if image is None or event.patch.get("project_id") != image.project_id:
            _fail()
        self.image(session, image, write=True)

    def backfill(self, session):
        count = 0
        for image in session.scalars(select(Image).order_by(Image.project_id, Image.image_revision_id)
                                     .execution_options(yield_per=128)):
            count += self.image(session, image, write=True)
        session.flush()
        return count
