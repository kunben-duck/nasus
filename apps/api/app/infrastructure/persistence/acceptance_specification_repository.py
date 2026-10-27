from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...domain.quality_loop.acceptance_specification import (
    AC_TOOL, AcceptanceRevision, AcceptanceIntegrityError, StaleAcceptanceSpecification,
    ObservableOracle, acceptance_identity, acceptance_digest, require_authority_decision,
)
from .acceptance_specification_models import AcceptanceRevisionRecord
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord
from .document_projection_models import SourceDocumentRevisionRecord
from .image_revision_models import ImageRevisionRecord, ImageObjectMemberRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class PinnedRequirementAuthorityRepository:
    record_type = AcceptanceRevisionRecord
    revision_type = AcceptanceRevision
    id_field = "ac_id"
    identity = staticmethod(acceptance_identity)
    tool_id = AC_TOOL
    document_kind = "acceptance_criterion"
    required_basis = "user_confirmed_requirement"
    event_prefix = "quality.acceptance_specification"
    entity_type = "acceptance_specification"
    query_key = "acceptance-specification"

    @classmethod
    def _value(cls, row):
        try:
            value = cls.revision_type(**row.payload)
            if (value.digest != row.content_hash or any(getattr(row, k) != getattr(value, k) for k in (
                    "revision_id", cls.id_field, "project_id", "image_revision_id", "object_id", "binding_id", "source_revision_id",
                    "document_revision_id", "previous_revision_id", "sequence", "status", "invocation_id"))):
                raise ValueError("metadata mismatch")
            return value
        except (ValueError, TypeError, KeyError) as exc:
            raise AcceptanceIntegrityError("stored acceptance revision failed verification") from exc

    @classmethod
    def _history(cls, session, project_id, ac_id, through_revision_id=None, *, reuse_snapshot=False):
        model = cls.record_type
        query = select(model).where(model.project_id == project_id, getattr(model, cls.id_field) == ac_id)
        if through_revision_id is not None:
            row = session.get(model, through_revision_id)
            if row is None or (row.project_id, getattr(row, cls.id_field)) != (project_id, ac_id):
                raise KeyError("acceptance revision not found")
            query = query.where(model.sequence <= row.sequence)
        rows = session.scalars(query.order_by(model.sequence).limit(1001)).all()
        values = tuple(cls._value(row) for row in rows)
        if len(values) > 1000:
            raise AcceptanceIntegrityError("acceptance history exceeds budget")
        for index, value in enumerate(values):
            if (value.sequence != index + 1 or value.previous_revision_id != (values[index - 1].revision_id if index else None)
                    or (value.status == "withdrawn" and (index == 0 or values[index - 1].status != "approved"))):
                raise AcceptanceIntegrityError("acceptance history is incomplete")
        from .authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1
        AuthorityProvenanceProjectorV1().facts(session,
            "acceptance" if cls.id_field == "ac_id" else "business_rule", rows[-1:], write=False,
            reuse_snapshot=reuse_snapshot)
        return values

    def history(self, project_id, ac_id, through_revision_id=None):
        with session_scope() as session:
            return self._history(session, project_id, ac_id, through_revision_id, reuse_snapshot=True)

    def get(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(self.record_type, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("acceptance revision not found")
            history = self._history(session, project_id, getattr(row, self.id_field), revision_id, reuse_snapshot=True)
            if not history or history[-1].revision_id != revision_id:
                raise AcceptanceIntegrityError("acceptance revision is outside its history")
            return history[-1], row.artifact_ref

    @classmethod
    def _canonical(cls, session, request, invocation_id):
        row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        if (row is None or row.tool_id != cls.tool_id or row.status != "running" or row.input_payload.get("confirmed_by_user") is not True
                or any(k not in row.input_payload or row.input_payload[k] != v for k, v in request.model_dump(mode="json").items())):
            raise AcceptanceIntegrityError("acceptance review requires the confirmed canonical command")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise AcceptanceIntegrityError("acceptance conversation scope mismatch")
        if row.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, row.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != row.conversation_id:
                raise AcceptanceIntegrityError("acceptance goal scope mismatch")

    @classmethod
    def _frozen(cls, session, request, basis):
        image = session.get(ImageRevisionRecord, request.image_revision_id)
        member = session.scalar(select(ImageObjectMemberRecord).where(ImageObjectMemberRecord.image_revision_id == request.image_revision_id,
                                                                    ImageObjectMemberRecord.object_id == request.object_id))
        document = session.get(SourceDocumentRevisionRecord, basis["document_revision_id"])
        if (image is None or image.project_id != request.project_id or image.artifact_hash != request.image_artifact_hash
                or member is None or member.project_id != request.project_id or member.kind != "source_document"
                or document is None or document.kind != cls.document_kind or acceptance_digest(basis) != request.basis_digest
                or any(basis[k] != getattr(request, k) for k in ("project_id", "image_revision_id", "image_artifact_hash", "object_id"))
                or any(basis[k] != getattr(member, k) for k in ("binding_id", "source_revision_id", "document_revision_id"))
                or any(basis[k] != getattr(document, k) for k in ("project_id", "binding_id", "source_revision_id", "entity_id", "payload_hash", "parent_document_revision_id"))
                or not set(basis["evidence_ids"]).issubset(member.evidence_ids)):
            raise AcceptanceIntegrityError("acceptance authority source is not frozen")

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(cls.record_type).where(cls.record_type.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._value(row)
        if (value.authority_actor != actor_id or value.previous_revision_id != request.expected_previous_revision_id
                or value.status != ("approved" if request.decision == "approve" else "withdrawn")
                or any(getattr(value, key) != getattr(request, key) for key in (
                    "project_id", "image_revision_id", "image_artifact_hash", "object_id", "basis_digest", "policy_revision"))):
            raise AcceptanceIntegrityError("acceptance invocation is already bound to another decision")
        history = cls._history(session, request.project_id, getattr(value, cls.id_field), value.revision_id)
        if not history or history[-1] != value:
            raise AcceptanceIntegrityError("committed acceptance revision is outside its history")
        return value

    def committed(self, request, basis, *, actor_id, invocation_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._canonical(session, request, invocation_id)
            self._frozen(session, request, basis)
            value = self._committed(session, request, actor_id, invocation_id)
            require_current()
            return value

    def record(self, request, basis, *, actor_id, invocation_id, recorded_at, artifact_ref, artifact_hash, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._canonical(session, request, invocation_id)
            self._frozen(session, request, basis)
            replay = self._committed(session, request, actor_id, invocation_id)
            if replay is not None:
                require_current()
                return replay
            ac_id = self.identity(request.project_id, request.image_revision_id, request.object_id)
            history = self._history(session, request.project_id, ac_id)
            if (history[-1].revision_id if history else None) != request.expected_previous_revision_id:
                raise StaleAcceptanceSpecification("acceptance authority changed; inspect again")
            require_authority_decision(request.decision, ObservableOracle(**request.oracle.model_dump()) if request.oracle else None,
                request.authority_basis, history[-1].status if history else None, required_basis=self.required_basis)
            value = self.revision_type(str(uuid4()), ac_id, request.project_id, request.image_revision_id, request.image_artifact_hash,
                request.object_id, basis["binding_id"], basis["source_revision_id"], basis["document_revision_id"], request.basis_digest,
                "approved" if request.decision == "approve" else "withdrawn", request.expected_previous_revision_id, len(history) + 1,
                actor_id, invocation_id, recorded_at, artifact_hash)
            row = self.record_type(**{k: getattr(value, k) for k in (
                "revision_id", self.id_field, "project_id", "image_revision_id", "object_id", "binding_id", "source_revision_id", "document_revision_id",
                "previous_revision_id", "sequence", "status", "invocation_id")}, payload=asdict(value), content_hash=value.digest, artifact_ref=artifact_ref)
            session.add(row)
            session.flush()
            from .authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1
            AuthorityProvenanceProjectorV1().facts(session,
                "acceptance" if self.id_field == "ac_id" else "business_rule", (row,),
                write=True, new_revision=value.revision_id)
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=self.event_prefix + ".reviewed",
                occurred_at=recorded_at, correlation_id=request.project_id, entity_type=self.entity_type, entity_id=value.revision_id,
                entity_version=value.sequence, mutation_kind="append", patch={"project_id": request.project_id, self.id_field: ac_id,
                    "revision_id": value.revision_id, "image_revision_id": request.image_revision_id, "status": value.status},
                query_keys=[[self.query_key, request.project_id]]), session=session)
            session.flush()
            require_current()
            return value


class AcceptanceSpecificationRepository(PinnedRequirementAuthorityRepository):
    pass
