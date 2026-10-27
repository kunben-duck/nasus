"""Native frozen retrieval ancestry; no model, object-store, ACL or read-time repair."""
from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.system_image.context_pack_inputs import ContextCompileInput
from ...application.system_image.index_inputs import INDEX_BUILD_TOOL, IndexBuildRequest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.retrieval_index import validate_vectors
from ...domain.system_image.retrieval_provenance import retrieval_registration, require_retrieval_provenance as require
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_pack_models import ContextPackRecord as Context
from .document_projection_models import SourceDocumentRevisionRecord as SourceDocument
from .db_models import ToolInvocationRecord as Command, SSEEventOutboxRecord as Outbox
from .frozen_index_models import (FrozenIndexReservationRecord as Reservation, FrozenIndexGenerationRecord as Generation,
    FrozenIndexDocumentRecord as Document, FrozenRetrievalRecord as Trace)
from .image_publication_models import ImagePublicationRecord as Publication
from .image_revision_models import ImageObjectMemberRecord as Member
from .object_provenance_models import ObjectProvenanceNodeRecord as ObjectNode
from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
from .retrieval_provenance_models import (RetrievalProvenanceRecord as Anchor,
    IndexDocumentDependencyRecord as DocumentEdge, ContextRetrievalDependencyRecord as ContextEdge)


_NATIVE_FIELDS = {
    "reservation": ("invocation_id", "project_id", "baseline_id", "publication_id", "image_revision_id",
        "input_digest", "model_config_digest", "content_hash", "payload"),
    "generation": ("generation_id", "project_id", "publication_id", "dimensions", "document_count",
        "artifact_ref", "artifact_hash", "created_at"),
    "retrieval": ("retrieval_id", "project_id", "generation_id", "publication_id", "actor_id",
        "scope_fingerprint", "query_hash", "artifact_ref", "artifact_hash", "created_at"),
}
_DOCUMENT_FIELDS = ("generation_id", "document_id", "project_id", "object_id", "source_revision_id",
    "binding_id", "text", "document_hash", "vector_hash")


def _values(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class RetrievalProvenanceProjectorV1:
    def fact(self, session, kind, row, *, write=False):
        try:
            return self._fact(session, kind, row, write=write)
        except ImageRevisionIntegrityError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ImageRevisionIntegrityError("Retrieval provenance failed integrity verification") from error

    def _fact(self, session, kind, row, *, write):
        require(row is not None and kind in _NATIVE_FIELDS)
        native = {key: getattr(row, key) for key in _NATIVE_FIELDS[kind]}
        ident = native[{"reservation": "invocation_id", "generation": "generation_id", "retrieval": "retrieval_id"}[kind]]
        project = row.project_id
        publication = session.get(Publication, row.publication_id)
        require(publication is not None and publication.project_id == project)
        publication_anchor = PublicationProvenanceProjectorV1().fact(session, "publication", publication)
        pin = {key: publication.payload[key] for key in ("publication_id", "baseline_id", "image_revision_id",
            "image_artifact_hash", "manifest_id", "manifest_hash", "sequence", "quality_generation_authorized", "release_authorized")}
        parent, documents, edges = None, (), []
        if kind == "reservation":
            command = session.get(Command, ident)
            payload = row.payload
            require(command is not None and command.tool_id == INDEX_BUILD_TOOL
                and command.input_payload.get("confirmed_by_user") is True)
            request = IndexBuildRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key in IndexBuildRequest.model_fields})
            require(snapshot_digest(payload) == row.content_hash and payload["request"] == request.model_dump()
                and payload["pin"] == pin and payload["invocation_id"] == ident
                and payload["preview"]["request"] == payload["request"]
                and payload["preview"]["publication_pin"] == pin
                and payload["preview"]["model"]["config_digest"] == row.model_config_digest
                and payload["request"]["input_digest"] == row.input_digest
                and payload["request"]["model_config_digest"] == row.model_config_digest
                and (request.project_id, request.publication_id, row.image_revision_id, row.baseline_id)
                    == (project, row.publication_id, pin["image_revision_id"], pin["baseline_id"]))
        else:
            model, parent_kind, parent_id = (Reservation, "reservation", ident) if kind == "generation" else (
                Generation, "generation", row.generation_id)
            prior = session.get(model, parent_id)
            require(prior is not None and prior.project_id == project and prior.publication_id == row.publication_id)
            registered = self.fact(session, parent_kind, prior)
            parent = (parent_kind, parent_id, registered["content_hash"])
            if kind == "generation":
                documents, edges = self._documents(session, row, pin)
            else:
                require(type(row.actor_id) is str and bool(row.actor_id)
                    and type(row.scope_fingerprint) is str and bool(row.scope_fingerprint)
                    and row.query_hash.startswith("sha256:") and row.artifact_hash.startswith("sha256:"))
        expected = retrieval_registration(project_id=project, kind=kind, artifact_id=ident,
            metadata_hash=snapshot_digest(native), publication_pin=pin,
            publication_registration_hash=publication_anchor["content_hash"], parent=parent, documents=documents)
        saved = session.get(Anchor, (project, kind, ident))
        if saved is None:
            require(write)
            session.add(Anchor(**expected))
            session.flush()
        else:
            require(_values(saved) == expected)
        if kind == "generation":
            edges = [dict(project_id=project, generation_id=ident, generation_kind="generation",
                generation_hash=expected["content_hash"], **edge) for edge in edges]
            existing = [_values(e) for e in session.scalars(select(DocumentEdge).where(
                DocumentEdge.project_id == project, DocumentEdge.generation_id == ident).order_by(DocumentEdge.document_id))]
            if saved is None:
                require(write and not existing)
                session.add_all(DocumentEdge(**edge) for edge in edges)
                session.flush()
            else:
                require(existing == edges)
        return expected

    @staticmethod
    def _documents(session, generation, pin):
        project, ident, image_id = generation.project_id, generation.generation_id, pin["image_revision_id"]
        rows = session.execute(select(*(getattr(Document, key) for key in _DOCUMENT_FIELDS), Document.embedding).where(
            Document.project_id == project, Document.generation_id == ident).order_by(Document.document_id)).all()
        require(type(generation.document_count) is int and 0 < generation.document_count <= 4096
            and len(rows) == generation.document_count)
        members = {m.object_id: m for m in session.scalars(select(Member).where(
            Member.project_id == project, Member.image_revision_id == image_id))}
        nodes = {n.node_key: n.content_hash for n in session.execute(select(ObjectNode.node_key, ObjectNode.content_hash).where(
            ObjectNode.project_id == project, ObjectNode.kind == "member",
            ObjectNode.artifact_id.startswith(image_id + "/")))}
        documents, edges = [], []
        for row in rows:
            member = members.get(row.object_id)
            require(member is not None and member.kind in {"code_entity", "source_document"}
                and (member.binding_id, member.source_revision_id) == (row.binding_id, row.source_revision_id))
            key = "member:" + image_id + "/" + row.object_id
            require(key in nodes)
            vector = validate_vectors([row.embedding.tolist()], 1, generation.dimensions)[0]
            require(snapshot_digest(list(vector)) == row.vector_hash)
            digest = snapshot_digest({key: getattr(row, key) for key in _DOCUMENT_FIELDS})
            documents.append((row.document_id, digest, nodes[key]))
            edges.append(dict(document_id=row.document_id, document_hash=digest, member_key=key, member_hash=nodes[key]))
        return tuple(documents), edges

    def context(self, session, row, *, write=False):
        try:
            require(row is not None and snapshot_digest(row.payload) == row.content_hash)
            command = session.get(Command, row.invocation_id)
            require(command is not None and command.tool_id == "system_image.context.compile")
            request = ContextCompileInput.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
            require(request.project_id == row.project_id and request.image_revision_id == row.image_revision_id
                and row.request_hash == snapshot_digest(request.model_dump(mode="json"))
                and all(row.payload.get(key) == getattr(row, key) for key in
                    ("project_id", "context_id", "image_revision_id", "invocation_id"))
                and row.payload["image_artifact_hash"] == request.image_artifact_hash
                and row.payload["policy_revision"] == request.policy_revision)
            expected, cache = [], {}
            bindings = {} if request.retrieval_bindings is None else request.retrieval_bindings
            if request.retrieval_bindings is not None:
                targets = set(session.scalars(select(Member.object_id).join(SourceDocument,
                    Member.document_revision_id == SourceDocument.document_revision_id).where(
                        Member.project_id == row.project_id, Member.image_revision_id == row.image_revision_id,
                        Member.kind == "source_document", SourceDocument.kind == "acceptance_criterion")))
                require(set(bindings) == targets)
            for target, trace_id in sorted(bindings.items()):
                if trace_id not in cache:
                    trace = session.get(Trace, trace_id)
                    require(trace is not None and trace.project_id == row.project_id
                        and trace.publication_id == request.publication_id)
                    cache[trace_id] = self.fact(session, "retrieval", trace)
                pin = cache[trace_id]
                require(pin["image_revision_id"] == row.image_revision_id
                    and pin["image_artifact_hash"] == request.image_artifact_hash)
                value = dict(project_id=row.project_id, context_id=row.context_id, target_object_id=target,
                    image_revision_id=row.image_revision_id, context_metadata_hash=row.content_hash,
                    context_request_hash=row.request_hash, retrieval_kind="retrieval", retrieval_id=trace_id,
                    retrieval_hash=pin["content_hash"])
                expected.append({**value, "content_hash": snapshot_digest(value)})
            saved = [_values(e) for e in session.scalars(select(ContextEdge).where(
                ContextEdge.project_id == row.project_id, ContextEdge.context_id == row.context_id).order_by(ContextEdge.target_object_id))]
            if expected and not saved:
                require(write)
                session.add_all(ContextEdge(**edge) for edge in expected)
                session.flush()
            else:
                require(saved == expected)
        except ImageRevisionIntegrityError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ImageRevisionIntegrityError("Retrieval context dependency failed integrity verification") from error

    def backfill(self, session):
        for kind, model, key in (("reservation", Reservation, Reservation.invocation_id),
                                ("generation", Generation, Generation.generation_id), ("retrieval", Trace, Trace.retrieval_id)):
            after = None
            while True:
                query = select(model).order_by(key).limit(64)
                rows = session.scalars(query.where(key > after) if after else query).all()
                if not rows:
                    break
                for row in rows:
                    self.fact(session, kind, row, write=True)
                after = getattr(rows[-1], key.key)
        after = None
        while True:
            query = select(Context).order_by(Context.context_id).limit(64)
            rows = session.scalars(query.where(Context.context_id > after) if after else query).all()
            if not rows:
                break
            for row in rows:
                self.context(session, row, write=True)
            after = rows[-1].context_id

    def project_event(self, session, event):
        kind = {"system_image.index.reserved": "reservation", "system_image.index.completed": "generation"}.get(event.event_type)
        if kind:
            model = Reservation if kind == "reservation" else Generation
            row = session.get(model, event.entity_id)
            require(row is not None and event.entity_type == "image_index" and event.mutation_kind == "append"
                and event.patch == {"project_id": row.project_id, "generation_id": event.entity_id}
                and event.correlation_id == row.project_id)
            self.fact(session, kind, row)
        elif event.event_type == "system_image.context.compiled":
            row = session.get(Context, event.entity_id)
            sequence = session.scalar(select(Outbox.sequence).where(Outbox.event_id == event.event_id))
            require(row is not None and event.entity_type == "context_pack" and event.mutation_kind == "append"
                and event.correlation_id == row.project_id and sequence is not None and event.entity_version == sequence
                and event.patch == {key: row.payload[key] for key in
                    ("context_id", "project_id", "image_revision_id", "readiness")})
            self.context(session, row)
