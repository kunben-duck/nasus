from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.requirement_review_models import EVALUATE_REQUIREMENT, CONFIRM_REQUIREMENT
from ...domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import AuditEventRecord, ToolInvocationRecord, VersionRecord
from .event_outbox_repository import EventOutboxRepository
from .image_publication_repository import ImagePublicationRepository
from .requirement_revision_models import RequirementRevisionRecord
from .requirement_revision_repository import RequirementRevisionRepository
from .requirement_review_models import RequirementReviewEventRecord as Event
from .version_delivery_repository import VersionDeliveryRepository
from .unit_of_work import session_scope


class RequirementReviewRepository:
    def __init__(self, projection=None):
        self.projection = projection

    @staticmethod
    def _event(row):
        if snapshot_digest(row.payload) != row.content_hash:
            raise VersionDeliveryIntegrityError("Requirement review digest mismatch")
        return {"event_id": row.event_id, "kind": row.kind, "actor_id": row.actor_id,
            "invocation_id": row.invocation_id, "recorded_at": row.recorded_at,
            "revision_id": row.revision_id, "payload": deepcopy(row.payload), "content_hash": row.content_hash}

    def revision(self, selection, *, latest=True):
        with session_scope() as session:
            row = session.get(RequirementRevisionRecord, selection.revision_id)
            if row is None or (row.project_id, row.version_id) != (selection.project_id, selection.version_id):
                raise KeyError("Requirement revision not found in this iteration")
            if latest:
                head = session.scalar(select(RequirementRevisionRecord.revision_id).where(
                    RequirementRevisionRecord.us_id == row.us_id).order_by(RequirementRevisionRecord.sequence.desc()).limit(1))
                if head != row.revision_id:
                    raise VersionDeliveryConflict("Requirement changed; select the latest revision")
            return RequirementRevisionRepository._view(session, row)

    def events(self, selection):
        with session_scope() as session:
            rows = session.scalars(select(Event).where(Event.project_id == selection.project_id,
                Event.version_id == selection.version_id, Event.revision_id == selection.revision_id)
                .order_by(Event.recorded_at, Event.event_id)).all()
            return [self._event(row) for row in rows]

    def record(self, request, revision, kind, payload, *, invocation_id, scope, check, complete=False, assessment=None):
        with session_scope() as session:
            ImagePublicationRepository._lock(session, request.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            expected_tool = CONFIRM_REQUIREMENT if kind == "confirmed" else EVALUATE_REQUIREMENT
            if (command is None or command.tool_id != expected_tool or command.status != "running"
                    or command.input_payload.get("confirmed_by_user") is not True
                    or any(command.input_payload.get(key) != value for key, value in request.model_dump(mode="json").items())):
                raise VersionDeliveryIntegrityError("Review requires the exact confirmed canonical command")
            VersionDeliveryRepository._actor(session, request.project_id, scope.actor_id, scope.effective_project_role)
            session.scalar(select(VersionRecord).where(VersionRecord.id == request.version_id).with_for_update())
            head = session.scalar(select(RequirementRevisionRecord).where(RequirementRevisionRecord.us_id == revision.us_id)
                .order_by(RequirementRevisionRecord.sequence.desc()).limit(1))
            if head is None or head.revision_id != request.revision_id:
                raise VersionDeliveryConflict("Requirement changed while review was running")
            binding = VersionDeliveryRepository._binding(session, request.project_id, request.version_id)
            if binding is None or binding["iteration_image"]["image_revision_id"] != revision.image_revision_id:
                raise VersionDeliveryConflict("Iteration image changed during requirement review")
            if kind in {"evaluated", "failed"}:
                latest_attempt = session.scalar(select(Event).where(Event.revision_id == revision.revision_id,
                    Event.kind == "reserved").order_by(Event.recorded_at.desc(), Event.event_id.desc()).limit(1))
                if latest_attempt is None or latest_attempt.invocation_id != invocation_id:
                    raise VersionDeliveryConflict("A newer requirement review superseded this model call")
            check()
            prior = session.scalar(select(Event).where(Event.invocation_id == invocation_id, Event.kind == kind))
            if prior:
                if prior.payload != payload or prior.actor_id != scope.actor_id:
                    raise VersionDeliveryIntegrityError("Review command already has a different outcome")
                return self._event(prior)
            if assessment is not None and not any(item.blocking for item in assessment.questions):
                if self.projection is None:
                    raise RuntimeError("Requirement projection is unavailable")
                payload = {**payload, "projection": self.projection.create(revision, assessment,
                    invocation_id=invocation_id, actor_id=scope.actor_id, session=session)}
            now = session.scalar(select(func.clock_timestamp())).isoformat()
            row = Event(event_id="review_" + uuid4().hex, project_id=request.project_id, version_id=request.version_id,
                us_id=revision.us_id, revision_id=request.revision_id, invocation_id=invocation_id, kind=kind,
                actor_id=scope.actor_id, recorded_at=now, content_hash=snapshot_digest(payload), payload=deepcopy(payload))
            session.add(row)
            refs = ["requirement_revision:" + revision.revision_id, "requirement_review:" + row.event_id]
            if complete:
                command.status, command.summary = "completed", "Requirement " + kind + "; no execution or release authority granted."
                command.revision += 1
                command.result_payload = ToolResult(invocation_id=invocation_id, status="completed", summary=command.summary,
                    object_refs=refs).model_dump(mode="json")
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=scope.actor_id, actor_kind=command.initiator_actor,
                action="requirement." + kind, entity_type="requirement_review", entity_id=row.event_id, status="completed",
                summary="Requirement review event recorded", conversation_id=command.conversation_id,
                tool_invocation_id=invocation_id, object_refs=refs, evidence_refs=[], event_metadata={
                    "project_id": request.project_id, "version_id": request.version_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="requirement.review.updated", occurred_at=now,
                correlation_id=request.project_id, tool_invocation_id=invocation_id, entity_type="requirement_review",
                entity_id=row.event_id, entity_version=0, mutation_kind="append", patch={"project_id": request.project_id,
                    "version_id": request.version_id, "revision_id": revision.revision_id},
                query_keys=[["version-requirements", request.project_id, request.version_id],
                    ["requirement-review", revision.revision_id], ["version-delivery", request.project_id, request.version_id]]), session=session)
            session.flush()
            check()
            return self._event(row)
