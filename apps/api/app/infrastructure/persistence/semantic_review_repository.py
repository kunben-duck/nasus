from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import and_, exists, select, tuple_
from sqlalchemy.orm import aliased

from ...application.platform.tool_models import EventPayload
from ...application.system_image.semantic_screening import MAX_MATCHED_REVIEW_HEADS
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.link_decisions import StaleLinkDecision
from ...domain.system_image.semantic_review import SemanticDecision, SEMANTIC_REVIEW_TOOL, stored_semantic_assertion
from .db_models import AgentGoalRecord, ConversationRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .image_revision_models import ImageObjectMemberRecord
from .document_projection_models import SourceDocumentRevisionRecord
from .semantic_evaluation_models import SemanticEvaluationRecord, SemanticCallReservationRecord
from .semantic_evaluation_repository import SemanticEvaluationRepository
from .semantic_review_models import SemanticAssertionRecord, SemanticDecisionRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class SemanticReviewRepository:
    def matching_heads(self, project_id, predicate, subjects, target):
        if not subjects or len(subjects) > 10000 or predicate not in {"implements", "asserts"}:
            raise ValueError("invalid semantic review identity query")
        assertion, decision = SemanticAssertionRecord, SemanticDecisionRecord
        successor = aliased(SemanticDecisionRecord)
        subject_member, target_member = aliased(ImageObjectMemberRecord), aliased(ImageObjectMemberRecord)
        subject_doc, target_doc = aliased(SourceDocumentRevisionRecord), aliased(SourceDocumentRevisionRecord)
        subject_entity = subject_member.entity_id if predicate == "implements" else subject_doc.entity_id
        subject_kind = subject_member.kind if predicate == "implements" else subject_doc.kind
        query = (select(decision, subject_member.binding_id, subject_entity, subject_kind)
            .join(assertion, assertion.assertion_id == decision.assertion_id)
            .join(subject_member, and_(subject_member.image_revision_id == assertion.image_revision_id,
                                      subject_member.object_id == assertion.subject_object_id))
            .join(target_member, and_(target_member.image_revision_id == assertion.image_revision_id,
                                     target_member.object_id == assertion.object_id))
            .join(target_doc, target_doc.document_revision_id == target_member.document_revision_id))
        if predicate == "asserts":
            query = query.join(subject_doc, subject_doc.document_revision_id == subject_member.document_revision_id)
        query = query.where(decision.project_id == project_id, assertion.project_id == project_id,
            assertion.predicate == predicate, subject_member.project_id == project_id, target_member.project_id == project_id,
            target_member.binding_id == target.binding_id, target_doc.entity_id == target.entity_id, target_doc.kind == target.kind,
            tuple_(subject_member.binding_id, subject_entity, subject_kind).in_([s.identity_key for s in subjects]),
            ~exists(select(successor.decision_id).where(successor.previous_decision_id == decision.decision_id)))
        # Never truncate away a rejection. Over-budget histories fail closed.
        with session_scope() as session:
            rows = session.execute(query.order_by(decision.decision_id).limit(MAX_MATCHED_REVIEW_HEADS + 1)).all()
            if len(rows) > MAX_MATCHED_REVIEW_HEADS:
                raise ValueError("semantic review identity query exceeds its complete head budget")
            from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
            RelationFactProvenanceProjectorV1().facts(session, "semantic_review", tuple(row[0] for row in rows), write=False)
            identities = {s.identity_key: s.object_id for s in subjects}
            result = []
            for row, binding, entity, kind in rows:
                verified = self._decision(session, row)
                result.append((identities[(binding, entity, kind)], verified.decision_id, verified.digest))
            return tuple(sorted(result))

    def selected(self, project_id, decision_ids):
        from ...domain.system_image.semantic_membership import ImageSemanticMember
        with session_scope() as session:
            result = []
            rows = session.scalars(select(SemanticDecisionRecord).where(
                SemanticDecisionRecord.project_id == project_id, SemanticDecisionRecord.decision_id.in_(decision_ids))).all()
            from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
            RelationFactProvenanceProjectorV1().facts(session, "semantic_review", rows, write=False)
            for row in rows:
                decision = self._decision(session, row)
                assertion = self._assertion(session.get(SemanticAssertionRecord, decision.assertion_id))
                result.append(ImageSemanticMember(assertion, decision))
            return tuple(sorted(result, key=lambda item: item.claim_id))

    @staticmethod
    def _assertion(row):
        try:
            result = stored_semantic_assertion(row.payload)
        except (ValueError, TypeError, KeyError) as exc:
            raise ImageRevisionIntegrityError("stored semantic assertion is invalid") from exc
        if (result.digest != row.content_hash or any(getattr(result, key) != getattr(row, key) for key in (
                "assertion_id", "project_id", "claim_id", "evaluation_id", "image_revision_id", "subject_object_id", "object_id", "predicate"))):
            raise ImageRevisionIntegrityError("stored semantic assertion failed verification")
        return result

    @classmethod
    def _decision(cls, session, row):
        try:
            result = SemanticDecision(**row.payload)
        except (ValueError, TypeError, KeyError) as exc:
            raise ImageRevisionIntegrityError("stored semantic decision is invalid") from exc
        assertion_row = session.get(SemanticAssertionRecord, result.assertion_id)
        if assertion_row is None:
            raise ImageRevisionIntegrityError("semantic decision lost its assertion")
        assertion = cls._assertion(assertion_row)
        if (result.digest != row.content_hash or any(getattr(result, key) != getattr(row, key) for key in (
                "decision_id", "project_id", "claim_id", "assertion_id", "invocation_id", "previous_decision_id", "sequence"))
                or any(getattr(result, key) != getattr(assertion, key) for key in ("project_id", "claim_id", "evaluation_id", "image_revision_id", "evidence_digest"))
                or result.assertion_digest != assertion.digest):
            raise ImageRevisionIntegrityError("stored semantic decision failed verification")
        try:
            assertion.require_decision(result.decision)
        except ValueError as exc:
            raise ImageRevisionIntegrityError("stored semantic decision violates assertion policy") from exc
        return result

    @classmethod
    def _history(cls, session, project_id, claim_id, through_decision_id=None):
        if through_decision_id == "":
            return ()
        query = select(SemanticDecisionRecord).where(SemanticDecisionRecord.project_id == project_id, SemanticDecisionRecord.claim_id == claim_id)
        if through_decision_id is not None:
            head = session.get(SemanticDecisionRecord, through_decision_id)
            if head is None or (head.project_id, head.claim_id) != (project_id, claim_id):
                raise KeyError("semantic review head not found")
            query = query.where(SemanticDecisionRecord.sequence <= head.sequence)
        result = tuple(cls._decision(session, row) for row in session.scalars(query.order_by(SemanticDecisionRecord.sequence)))
        for i, decision in enumerate(result):
            if decision.sequence != i + 1 or decision.previous_decision_id != (result[i - 1].decision_id if i else None):
                raise ImageRevisionIntegrityError("semantic decision chain is incomplete")
        return result

    def history(self, project_id, claim_id, through_decision_id=None):
        with session_scope() as session:
            result = self._history(session, project_id, claim_id, through_decision_id)
            if result:
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "semantic_review",
                    (session.get(SemanticDecisionRecord, result[-1].decision_id),), write=False)
            return result

    @staticmethod
    def _canonical(session, request, invocation_id):
        invocation = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        if (invocation is None or invocation.tool_id != SEMANTIC_REVIEW_TOOL or invocation.status != "running"
                or invocation.input_payload.get("confirmed_by_user") is not True
                or any(key not in invocation.input_payload or invocation.input_payload[key] != value for key, value in request.model_dump().items())):
            raise ImageRevisionIntegrityError("semantic review requires the confirmed canonical command")
        if invocation.conversation_id:
            conversation = session.get(ConversationRecord, invocation.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ImageRevisionIntegrityError("semantic review conversation scope mismatch")
        if invocation.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, invocation.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != invocation.conversation_id:
                raise ImageRevisionIntegrityError("semantic review goal scope mismatch")

    @staticmethod
    def _frozen(session, assertion):
        evaluation = session.get(SemanticEvaluationRecord, assertion.evaluation_id)
        reservation = session.get(SemanticCallReservationRecord, assertion.evaluation_id)
        if (evaluation is None or reservation is None or evaluation.project_id != assertion.project_id
                or evaluation.artifact_hash != assertion.evaluation_artifact_hash):
            raise ImageRevisionIntegrityError("semantic review requires a committed evaluation")
        selection = SemanticEvaluationRepository._payload(reservation)["request"]
        if (selection["project_id"] != assertion.project_id or selection["image_revision_id"] != assertion.image_revision_id
                or selection["expected_image_hash"] != assertion.image_artifact_hash or selection["input_digest"] != assertion.input_digest
                or selection["target_object_id"] != assertion.object_id or selection["relation"] != assertion.predicate
                or assertion.subject_object_id not in selection["subject_object_ids"]):
            raise ImageRevisionIntegrityError("semantic assertion differs from the frozen evaluation")
        for object_id, revision, evidence, kind in (
                (assertion.subject_object_id, assertion.subject_revision_id, assertion.subject_evidence_ids, "code_entity" if assertion.predicate == "implements" else "source_document"),
                (assertion.object_id, assertion.object_revision_id, assertion.object_evidence_ids, "source_document")):
            member = session.scalar(select(ImageObjectMemberRecord).where(ImageObjectMemberRecord.image_revision_id == assertion.image_revision_id,
                                                                          ImageObjectMemberRecord.object_id == object_id))
            if (member is None or member.project_id != assertion.project_id or member.kind != kind
                    or (member.entity_revision_id if kind == "code_entity" else member.document_revision_id) != revision
                    or not set(evidence).issubset(member.evidence_ids)):
                raise ImageRevisionIntegrityError("semantic assertion endpoint is not frozen")

    def record(self, request, assertion, *, actor_id, invocation_id, recorded_at, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._canonical(session, request, invocation_id)
            self._frozen(session, assertion)
            assertion.require_decision(request.decision)
            if (request.project_id, request.evaluation_id, request.subject_object_id, request.assertion_id, request.assertion_digest, request.evidence_digest) != (
                    assertion.project_id, assertion.evaluation_id, assertion.subject_object_id, assertion.assertion_id, assertion.digest, assertion.evidence_digest):
                raise ImageRevisionIntegrityError("semantic review pins differ from the assertion")
            history = self._history(session, request.project_id, assertion.claim_id)
            replay = session.scalar(select(SemanticDecisionRecord).where(SemanticDecisionRecord.invocation_id == invocation_id))
            if replay is not None:
                result = self._decision(session, replay)
                if (result not in history or result.assertion_id != assertion.assertion_id or result.reviewer_actor != actor_id
                        or result.decision != request.decision or result.reason != request.reason
                        or result.previous_decision_id != request.expected_previous_decision_id):
                    raise ImageRevisionIntegrityError("semantic review invocation already bound")
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "semantic_review", (replay,), write=False)
                require_current()
                return result
            if (history[-1].decision_id if history else None) != request.expected_previous_decision_id:
                raise StaleLinkDecision("Semantic review changed; reload the exact claim history.")
            row = session.get(SemanticAssertionRecord, assertion.assertion_id)
            if row is None:
                session.add(SemanticAssertionRecord(**{key: getattr(assertion, key) for key in (
                    "assertion_id", "project_id", "claim_id", "evaluation_id", "image_revision_id", "subject_object_id", "object_id", "predicate")},
                    payload=asdict(assertion), content_hash=assertion.digest))
                session.flush()
            elif self._assertion(row) != assertion:
                raise ImageRevisionIntegrityError("semantic assertion identity collision")
            result = SemanticDecision(str(uuid4()), request.project_id, assertion.claim_id, assertion.assertion_id, assertion.digest,
                assertion.evidence_digest, assertion.evaluation_id, assertion.image_revision_id, request.decision, request.reason,
                actor_id, recorded_at, invocation_id, request.expected_previous_decision_id, len(history) + 1)
            session.add(SemanticDecisionRecord(**{key: getattr(result, key) for key in (
                "decision_id", "project_id", "claim_id", "assertion_id", "previous_decision_id", "sequence", "invocation_id")}, payload=asdict(result), content_hash=result.digest))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.semantic.reviewed",
                occurred_at=recorded_at, correlation_id=request.project_id, entity_type="semantic_link_decision", entity_id=result.decision_id,
                entity_version=0, mutation_kind="append", patch={"project_id": request.project_id, "claim_id": assertion.claim_id,
                    "assertion_id": assertion.assertion_id, "decision_id": result.decision_id},
                query_keys=[["semantic-reviews", request.project_id]]), session=session)
            session.flush()
            require_current()
            return result
