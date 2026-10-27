from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.semantic_evaluations import SEMANTIC_EVALUATE_TOOL
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import AgentGoalRecord, ConversationRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .image_revision_models import ImageRevisionRecord, ImageObjectMemberRecord
from .semantic_evaluation_models import SemanticCallReservationRecord, SemanticEvaluationRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class SemanticEvaluationRepository:
    @staticmethod
    def _invocation(session, request, invocation_id):
        invocation = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        if (invocation is None or invocation.tool_id != SEMANTIC_EVALUATE_TOOL or invocation.status != "running"
                or invocation.input_payload.get("confirmed_by_user") is not True
                or any(invocation.input_payload.get(key) != value for key, value in request.model_dump().items())):
            raise ImageRevisionIntegrityError("model egress requires the confirmed canonical request")
        if invocation.conversation_id:
            conversation = session.get(ConversationRecord, invocation.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ImageRevisionIntegrityError("semantic conversation scope mismatch")
        if invocation.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, invocation.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != invocation.conversation_id:
                raise ImageRevisionIntegrityError("semantic goal scope mismatch")
        return invocation

    @staticmethod
    def _payload(row):
        payload = row.payload
        if (not isinstance(payload, dict) or payload.get("schema") != "nasus.semantic-egress-reservation.v1"
                or snapshot_digest(payload) != row.content_hash or payload["invocation_id"] != row.invocation_id
                or payload["request"]["project_id"] != row.project_id
                or payload["request"]["image_revision_id"] != row.image_revision_id):
            raise ImageRevisionIntegrityError("semantic reservation integrity mismatch")
        return payload

    def get(self, project_id, invocation_id):
        with session_scope() as session:
            reservation = session.get(SemanticCallReservationRecord, invocation_id)
            if reservation is None:
                return None
            if reservation.project_id != project_id:
                raise KeyError("semantic reservation not found")
            result = dict(self._payload(reservation))
            saved = session.get(SemanticEvaluationRecord, invocation_id)
            if saved:
                if saved.project_id != project_id:
                    raise ImageRevisionIntegrityError("semantic result project mismatch")
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "evaluation", (saved,), write=False)
                result.update(artifact_ref=saved.artifact_ref, artifact_hash=saved.artifact_hash)
            return result

    def list_for_target(self, project_id, image_revision_id, target_object_id, relation, after_id, limit):
        row = SemanticCallReservationRecord
        with session_scope() as session:
            rows = session.execute(select(row, SemanticEvaluationRecord).outerjoin(
                SemanticEvaluationRecord, SemanticEvaluationRecord.invocation_id == row.invocation_id).where(
                row.project_id == project_id, row.image_revision_id == image_revision_id, row.invocation_id > after_id,
                row.payload["request"]["target_object_id"].as_string() == target_object_id,
                row.payload["request"]["relation"].as_string() == relation).order_by(row.invocation_id).limit(limit)).all()
            result = []
            from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
            RelationFactProvenanceProjectorV1().facts(session, "evaluation",
                tuple(saved for _, saved in rows if saved is not None), write=False)
            for reservation, saved in rows:
                payload = self._payload(reservation)
                result.append({"invocation_id": reservation.invocation_id, "request": payload["request"],
                    "model_name": payload["preview"]["model_name"], "recorded_at": payload["reserved_at"],
                    "state": "archived" if saved else "incomplete", "artifact_hash": saved.artifact_hash if saved else None})
            return result

    def reserve(self, request, preview, prepared, *, invocation_id, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            invocation = self._invocation(session, request, invocation_id)
            if session.get(SemanticCallReservationRecord, invocation_id) is not None:
                raise ValueError("model call already reserved; do not retry an uncertain outcome")
            confirmed = datetime.fromisoformat(str(invocation.input_payload.get("confirmed_at", "")))
            if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                raise ValueError("model egress confirmation expired")
            image = session.get(ImageRevisionRecord, request.image_revision_id)
            if (image is None or image.project_id != request.project_id or image.artifact_hash != request.expected_image_hash
                    or prepared.digest != request.input_digest or preview.request != request):
                raise ImageRevisionIntegrityError("semantic reservation image or input mismatch")
            members = {row.object_id: row for row in session.scalars(select(ImageObjectMemberRecord).where(
                ImageObjectMemberRecord.image_revision_id == request.image_revision_id))}
            for endpoint in (prepared.target, *prepared.subjects):
                member = members.get(endpoint.object_id)
                if (member is None or member.project_id != request.project_id
                        or (member.entity_revision_id if member.kind == "code_entity" else member.document_revision_id) != endpoint.revision_id
                        or member.source_revision_id != endpoint.source_revision_id
                        or not set(endpoint.evidence_ids).issubset(member.evidence_ids)):
                    raise ImageRevisionIntegrityError("semantic reservation endpoint is not frozen")
            payload = {"schema": "nasus.semantic-egress-reservation.v1", "invocation_id": invocation_id,
                "request": request.model_dump(), "preview": preview.model_dump(), "authorized_by": actor_id,
                "confirmed_at": invocation.input_payload["confirmed_at"], "reserved_at": datetime.now(timezone.utc).isoformat()}
            session.add(SemanticCallReservationRecord(invocation_id=invocation_id, project_id=request.project_id,
                image_revision_id=request.image_revision_id, payload=payload, content_hash=snapshot_digest(payload)))
            self._event(session, request, invocation_id, "system_image.semantic.call_reserved")
            session.flush()
            require_current()

    def complete(self, request, *, invocation_id, artifact_ref, artifact_hash, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._invocation(session, request, invocation_id)
            reservation = session.get(SemanticCallReservationRecord, invocation_id)
            if reservation is None or self._payload(reservation)["request"] != request.model_dump():
                raise ImageRevisionIntegrityError("semantic result lacks its exact reservation")
            old = session.get(SemanticEvaluationRecord, invocation_id)
            if old:
                if (old.project_id, old.artifact_ref, old.artifact_hash) != (request.project_id, artifact_ref, artifact_hash):
                    raise ImageRevisionIntegrityError("semantic invocation has different committed output")
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "evaluation", (old,), write=False)
            else:
                session.add(SemanticEvaluationRecord(invocation_id=invocation_id, project_id=request.project_id,
                                                    artifact_ref=artifact_ref, artifact_hash=artifact_hash))
                self._event(session, request, invocation_id, "system_image.semantic.evaluated")
            session.flush()
            require_current()

    @staticmethod
    def _event(session, request, invocation_id, event_type):
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=event_type,
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=request.project_id,
            entity_type="semantic_evaluation", entity_id=invocation_id, entity_version=0, mutation_kind="append",
            patch={"project_id": request.project_id, "invocation_id": invocation_id, "image_revision_id": request.image_revision_id},
            query_keys=[["system-image-semantic-evaluations", request.project_id, request.image_revision_id]]), session=session)
