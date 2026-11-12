from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.requirement_revision_models import (
    REVISE_REQUIREMENT, RequirementRevisionInput, RequirementRevisionView,
)
from ...domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import AuditEventRecord, ConversationRecord, ToolInvocationRecord, USWorkItemRecord, VersionRecord
from .event_outbox_repository import EventOutboxRepository
from .image_publication_repository import ImagePublicationRepository
from .requirement_revision_models import RequirementRevisionRecord as Revision
from .unit_of_work import session_scope
from .version_delivery_repository import VersionDeliveryRepository


class RequirementRevisionRepository:
    @staticmethod
    def _view(session, row):
        if snapshot_digest(row.payload) != row.content_hash:
            raise VersionDeliveryIntegrityError("Requirement revision digest mismatch")
        value = RequirementRevisionView.model_validate({**deepcopy(row.payload), "content_hash": row.content_hash})
        if any(getattr(value, key) != getattr(row, key) for key in (
                "project_id", "version_id", "us_id", "revision_id", "sequence", "previous_revision_id",
                "image_revision_id", "actor_id", "invocation_id")):
            raise VersionDeliveryIntegrityError("Requirement revision identity mismatch")
        us = session.get(USWorkItemRecord, row.us_id)
        if us is None or (us.project_id, us.version_id) != (row.project_id, row.version_id):
            raise VersionDeliveryIntegrityError("Requirement is outside its original iteration")
        return value

    @staticmethod
    def _canonical(session, request, invocation_id):
        command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        if command is None or command.tool_id != REVISE_REQUIREMENT or command.status != "running":
            raise VersionDeliveryIntegrityError("A running canonical requirement command is required")
        payload = {k: v for k, v in query_payload(command.input_payload, preserve=frozenset({"version_id", "us_id"})).items()
            if k not in {"confirmed_by_user", "confirmed_at"}}
        if RequirementRevisionInput.model_validate(payload) != request:
            raise VersionDeliveryIntegrityError("Requirement command inputs changed")
        conversation = session.get(ConversationRecord, command.conversation_id) if command.conversation_id else None
        if conversation is not None and conversation.project_id not in {None, request.project_id}:
            raise VersionDeliveryIntegrityError("Requirement conversation belongs to another project")
        return command

    def append(self, request, *, invocation_id, scope, require_current):
        with session_scope() as session:
            ImagePublicationRepository._lock(session, request.project_id)
            command = self._canonical(session, request, invocation_id)
            VersionDeliveryRepository._actor(session, request.project_id, scope.actor_id, scope.effective_project_role)
            version = session.scalar(select(VersionRecord).where(VersionRecord.project_id == request.project_id,
                VersionRecord.id == request.version_id).with_for_update())
            if version is None:
                raise KeyError("Version not found")
            binding = VersionDeliveryRepository._binding(session, request.project_id, request.version_id)
            if binding is None or (binding["iteration_image"]["image_revision_id"],
                    binding["iteration_image"]["image_artifact_hash"]) != (request.image_revision_id, request.image_artifact_hash):
                raise VersionDeliveryConflict("Requirement input image is not the selected iteration image")
            require_current()
            request_hash = snapshot_digest(request.model_dump(mode="json"))
            prior = session.scalar(select(Revision).where(Revision.invocation_id == invocation_id))
            if prior:
                if prior.request_hash != request_hash or prior.actor_id != scope.actor_id:
                    raise VersionDeliveryIntegrityError("Requirement command is already bound")
                return self._view(session, prior)
            parent = None
            if request.us_id:
                parent = session.scalar(select(Revision).where(Revision.project_id == request.project_id,
                    Revision.version_id == request.version_id, Revision.us_id == request.us_id)
                    .order_by(Revision.sequence.desc()).limit(1))
                if parent is None or parent.revision_id != request.expected_revision_id:
                    raise VersionDeliveryConflict("Requirement changed; reload the latest revision before editing")
                original = self._view(session, parent)
                old_questions = {item.question.strip() for item in original.clarification_answers}
                if not old_questions.issubset({item.question.strip() for item in request.clarification_answers}):
                    raise VersionDeliveryConflict("Previously answered questions must be retained or explicitly corrected")
                us = session.get(USWorkItemRecord, request.us_id)
            else:
                us = USWorkItemRecord(id="us_" + uuid4().hex, project_id=request.project_id, version_id=request.version_id,
                    title=request.title, owner=scope.actor_id, status="analysis", risk="medium", progress=0,
                    next_action="Requirement review pending; no approved test generation")
                session.add(us)
                version.us_total += 1
                session.flush()
            now = session.scalar(select(func.clock_timestamp())).isoformat()
            revision_id = "req_" + uuid4().hex
            value = {"project_id": request.project_id, "version_id": request.version_id,
                "revision_id": revision_id, "us_id": us.id, "sequence": parent.sequence + 1 if parent else 1,
                "previous_revision_id": parent.revision_id if parent else None,
                "image_revision_id": request.image_revision_id, "image_artifact_hash": request.image_artifact_hash,
                "title": request.title, "text": request.text,
                "original_text": original.original_text if parent else request.text,
                "clarification_answers": [item.model_dump(mode="json") for item in request.clarification_answers],
                "actor_id": scope.actor_id, "invocation_id": invocation_id, "recorded_at": now,
                "status": "draft", "generation_authorized": False}
            digest = snapshot_digest(value)
            row = Revision(**{key: value[key] for key in ("project_id", "version_id", "us_id", "revision_id",
                "sequence", "previous_revision_id", "image_revision_id", "invocation_id", "actor_id")},
                request_hash=request_hash, content_hash=digest, payload=value)
            session.add(row)
            us.title, us.status, us.progress = request.title, "analysis", 0
            us.next_action = "Requirement review pending; no approved test generation"
            refs = ["version:" + request.version_id, "us:" + us.id, "requirement_revision:" + revision_id]
            command.status, command.summary = "completed", "Requirement draft revision saved; evaluation and independent approval remain pending."
            command.revision += 1
            command.result_payload = ToolResult(invocation_id=invocation_id, status="completed", summary=command.summary,
                object_refs=refs, requires_followup=True, followup_reason="requirement_semantic_review_pending").model_dump(mode="json")
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=scope.actor_id, actor_kind=command.initiator_actor,
                action="requirement.revised", entity_type="requirement_revision", entity_id=revision_id, status="completed",
                summary=command.summary, conversation_id=command.conversation_id, tool_invocation_id=invocation_id,
                object_refs=refs, evidence_refs=[], event_metadata={"project_id": request.project_id, "version_id": request.version_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="requirement.revised", occurred_at=now,
                correlation_id=request.project_id, tool_invocation_id=invocation_id, entity_type="requirement_revision",
                entity_id=revision_id, entity_version=value["sequence"], mutation_kind="append",
                patch={"project_id": request.project_id, "version_id": request.version_id, "us_id": us.id, "revision_id": revision_id},
                query_keys=[["version-requirements", request.project_id, request.version_id], ["project", request.project_id]]), session=session)
            session.flush()
            require_current()
            return self._view(session, row)

    def list(self, project_id, version_id, *, us_id, offset, limit):
        with session_scope() as session:
            query = select(Revision).where(Revision.project_id == project_id, Revision.version_id == version_id)
            if us_id:
                query = query.where(Revision.us_id == us_id).order_by(Revision.sequence.desc())
            else:
                ranked = select(Revision.revision_id, func.row_number().over(partition_by=Revision.us_id,
                    order_by=Revision.sequence.desc()).label("rank")).where(Revision.project_id == project_id,
                    Revision.version_id == version_id).subquery()
                query = query.join(ranked, ranked.c.revision_id == Revision.revision_id).where(ranked.c.rank == 1).order_by(Revision.us_id)
            return [self._view(session, row) for row in session.scalars(query.offset(offset).limit(limit)).all()]
