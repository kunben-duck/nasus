from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.index_inputs import INDEX_BUILD_TOOL
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.retrieval_index import IndexDocument, fuse_ranks, validate_vectors
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord
from .event_outbox_repository import EventOutboxRepository
from .frozen_index_models import FrozenIndexReservationRecord as Reservation, FrozenIndexGenerationRecord as Generation
from .frozen_index_models import FrozenIndexDocumentRecord as Document, FrozenRetrievalRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class FrozenIndexRepository:
    @staticmethod
    def _reservation(row):
        payload = row.payload
        if (snapshot_digest(payload) != row.content_hash or payload["invocation_id"] != row.invocation_id
                or payload["request"]["project_id"] != row.project_id
                or payload["pin"]["baseline_id"] != row.baseline_id
                or payload["pin"]["publication_id"] != row.publication_id
                or payload["pin"]["image_revision_id"] != row.image_revision_id
                or payload["request"]["input_digest"] != row.input_digest
                or payload["request"]["model_config_digest"] != row.model_config_digest):
            raise ImageRevisionIntegrityError("index reservation integrity mismatch")
        return payload

    @staticmethod
    def _command(session, request, invocation_id, *, lock=True):
        statement = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        row = session.scalar(statement.with_for_update() if lock else statement)
        if (row is None or row.tool_id != INDEX_BUILD_TOOL or row.status != "running"
                or row.input_payload.get("confirmed_by_user") is not True
                or any(row.input_payload.get(key) != value for key, value in request.model_dump().items())):
            raise ImageRevisionIntegrityError("index write requires the confirmed canonical request")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ImageRevisionIntegrityError("index conversation scope mismatch")
        goal_id = row.input_payload.get("agent_goal_id")
        if goal_id:
            goal = session.get(AgentGoalRecord, goal_id)
            if goal is None or (goal.project_id, goal.conversation_id) != (request.project_id, row.conversation_id):
                raise ImageRevisionIntegrityError("index goal scope mismatch")
        return row

    def require_running(self, request, invocation_id):
        with session_scope() as session:
            self._command(session, request, invocation_id, lock=False)

    def reservation(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.get(Reservation, invocation_id)
            if row is None:
                return None
            if row.project_id != project_id:
                raise KeyError("index reservation not found")
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().fact(session, "reservation", row)
            return self._reservation(row)

    def reserve(self, request, pin, preview, *, invocation_id, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            command = self._command(session, request, invocation_id)
            if session.get(Reservation, invocation_id):
                raise ValueError("index call already reserved; uncertain calls cannot be retried")
            confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
            if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                raise ValueError("index consent expired")
            payload = {"invocation_id": invocation_id, "request": request.model_dump(), "pin": pin.model_dump(),
                "preview": preview, "authorized_by": actor_id, "confirmed_at": confirmed.isoformat()}
            row = Reservation(invocation_id=invocation_id, project_id=request.project_id, baseline_id=pin.baseline_id,
                publication_id=pin.publication_id, image_revision_id=pin.image_revision_id, input_digest=request.input_digest,
                model_config_digest=request.model_config_digest, content_hash=snapshot_digest(payload), payload=payload)
            session.add(row)
            session.flush()
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().fact(session, "reservation", row, write=True)
            self._event(session, request.project_id, invocation_id, "system_image.index.reserved")
            session.flush()
            require_current()

    def complete(self, request, *, invocation_id, documents, vectors, artifact_ref, artifact_hash, require_current):
        vectors = validate_vectors(vectors, len(documents))
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._command(session, request, invocation_id)
            row = session.get(Reservation, invocation_id)
            if row is None or self._reservation(row)["request"] != request.model_dump():
                raise ImageRevisionIntegrityError("index commit requires its original reservation")
            if session.get(Generation, invocation_id):
                raise ImageRevisionIntegrityError("index generation already committed")
            session.add(Generation(generation_id=invocation_id, project_id=request.project_id,
                publication_id=request.publication_id, dimensions=len(vectors[0]), document_count=len(documents),
                artifact_ref=artifact_ref, artifact_hash=artifact_hash, created_at=datetime.now(timezone.utc).isoformat()))
            session.flush()
            for doc, vector in zip(documents, vectors):
                session.add(Document(generation_id=invocation_id, project_id=request.project_id, document_id=doc.document_id,
                    object_id=doc.object_id, source_revision_id=doc.source_revision_id, binding_id=doc.binding_id,
                    text=doc.text, document_hash=doc.digest, vector_hash=snapshot_digest(list(vector)), embedding=list(vector)))
            session.flush()
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().fact(session, "generation", session.get(Generation, invocation_id), write=True)
            self._event(session, request.project_id, invocation_id, "system_image.index.completed")
            session.flush()
            require_current()

    @staticmethod
    def _generation(row):
        return {key: getattr(row, key) for key in ("generation_id", "project_id", "publication_id", "dimensions",
            "document_count", "artifact_ref", "artifact_hash", "created_at")}

    def get(self, project_id, generation_id):
        with session_scope() as session:
            row = session.get(Generation, generation_id)
            if row is None:
                return None
            if row.project_id != project_id:
                raise KeyError("index generation not found")
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().fact(session, "generation", row)
            return self._generation(row)

    def latest(self, project_id, publication_id):
        with session_scope() as session:
            row = session.scalar(select(Generation).where(Generation.project_id == project_id,
                Generation.publication_id == publication_id).order_by(Generation.created_at.desc(), Generation.generation_id.desc()).limit(1))
            if row is not None:
                from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
                RetrievalProvenanceProjectorV1().fact(session, "generation", row)
            return self._generation(row) if row else None

    def search(self, generation, query, vector, *, binding_ids, limit):
        docs = {item["document"]["document_id"]: item for item in generation["documents"]}
        vector = validate_vectors([vector], 1, generation["dimensions"])[0] if vector is not None else None
        with session_scope() as session:
            if session.get_bind().dialect.name != "postgresql":
                raise RuntimeError("versioned retrieval requires PostgreSQL/pgvector")
            filters = (Document.project_id == generation["project_id"], Document.generation_id == generation["generation_id"])
            rows = session.scalars(select(Document).where(*filters)).all()
            if len(rows) != len(docs):
                raise ImageRevisionIntegrityError("index document membership mismatch")
            for row in rows:
                expected = docs.get(row.document_id)
                if expected is None:
                    raise ImageRevisionIntegrityError("unexpected index document")
                doc = IndexDocument(**expected["document"])
                values = validate_vectors([row.embedding.tolist()], 1, generation["dimensions"])[0]
                if (doc.digest != row.document_hash or snapshot_digest(list(values)) != expected["vector_hash"]
                        or row.vector_hash != expected["vector_hash"] or row.text != doc.text
                        or (row.object_id, row.binding_id, row.source_revision_id) != (doc.object_id, doc.binding_id, doc.source_revision_id)):
                    raise ImageRevisionIntegrityError("index document or vector integrity mismatch")
            filters += (Document.binding_id.in_(binding_ids),)
            candidate_limit = min(4096, max(72, limit * 9))
            vector_ids = []
            if vector is not None:
                distance = Document.embedding.cosine_distance(list(vector))
                vector_ids = session.scalars(select(Document.document_id).where(*filters).order_by(distance, Document.document_id).limit(candidate_limit)).all()
            ts = func.to_tsvector("simple", Document.text)
            terms = func.websearch_to_tsquery("simple", query)
            lexical_ids = session.scalars(select(Document.document_id).where(*filters, ts.op("@@")(terms)).order_by(
                func.ts_rank_cd(ts, terms).desc(), Document.document_id).limit(candidate_limit)).all()
            return [{"document": docs[key]["document"], "score": score} for key, score in fuse_ranks(vector_ids, lexical_ids, limit=limit)]

    def append_trace(self, metadata, *, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, metadata["project_id"])
            row = FrozenRetrievalRecord(**metadata)
            session.add(row)
            session.flush()
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().fact(session, "retrieval", row, write=True)
            require_current()

    def trace(self, project_id, retrieval_id):
        with session_scope() as session:
            row = session.get(FrozenRetrievalRecord, retrieval_id)
            if row is None or row.project_id != project_id:
                raise KeyError("retrieval trace not found")
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().fact(session, "retrieval", row)
            return {column.name: getattr(row, column.name) for column in FrozenRetrievalRecord.__table__.columns}

    @staticmethod
    def _event(session, project_id, invocation_id, kind):
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind,
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=project_id,
            entity_type="image_index", entity_id=invocation_id, entity_version=0, mutation_kind="append",
            patch={"project_id": project_id, "generation_id": invocation_id},
            query_keys=[["system-image-index", project_id]]), session=session)
