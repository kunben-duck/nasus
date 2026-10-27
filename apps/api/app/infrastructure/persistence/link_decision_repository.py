from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.link_decisions import LinkDecision, REVIEW_LINK_TOOL, assertion_evidence_digest, require_expected_decision
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord
from .link_decision_models import LinkDecisionRecord
from .reference_link_models import ReferenceProposalRecord
from .reference_link_repository import ReferenceLinkRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope


class LinkDecisionRepository:
    def selected(self, project_id, proposal_id, decision_ids):
        if not 1 <= len(decision_ids) <= 1000:
            raise ValueError("invalid decision selection size")
        with session_scope() as session:
            rows = session.scalars(select(LinkDecisionRecord).where(
                LinkDecisionRecord.project_id == project_id, LinkDecisionRecord.proposal_id == proposal_id,
                LinkDecisionRecord.decision_id.in_(decision_ids)).order_by(LinkDecisionRecord.decision_id)).all()
            from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
            RelationFactProvenanceProjectorV1().facts(session, "reference_review", rows, write=False)
            return tuple(self._read(row) for row in rows)

    @staticmethod
    def _read(row):
        try:
            result = LinkDecision(**row.payload)
        except (TypeError, ValueError) as exc:
            raise ImageRevisionIntegrityError("invalid stored link decision") from exc
        if result.digest != row.content_hash or any(getattr(result, key) != getattr(row, key) for key in (
                "decision_id", "project_id", "proposal_id", "assertion_id", "previous_decision_id", "sequence", "invocation_id")):
            raise ImageRevisionIntegrityError("link decision integrity failure")
        return result

    @classmethod
    def _history(cls, session, project_id, proposal_id, assertion_id, through_decision_id=None):
        if through_decision_id == "":
            return ()
        query = select(LinkDecisionRecord).where(LinkDecisionRecord.project_id == project_id,
            LinkDecisionRecord.proposal_id == proposal_id, LinkDecisionRecord.assertion_id == assertion_id)
        if through_decision_id is not None:
            head = session.get(LinkDecisionRecord, through_decision_id)
            if head is None or (head.project_id, head.proposal_id, head.assertion_id) != (project_id, proposal_id, assertion_id):
                raise KeyError("review head not found")
            query = query.where(LinkDecisionRecord.sequence <= head.sequence)
        result = tuple(cls._read(row) for row in session.scalars(query.order_by(LinkDecisionRecord.sequence)))
        for i, item in enumerate(result):
            if item.sequence != i + 1 or item.previous_decision_id != (result[i - 1].decision_id if i else None):
                raise ImageRevisionIntegrityError("link decision chain is incomplete")
        return result

    def history(self, project_id, proposal_id, assertion_id, through_decision_id=None):
        with session_scope() as session:
            result = self._history(session, project_id, proposal_id, assertion_id, through_decision_id)
            if result:
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "reference_review",
                    (session.get(LinkDecisionRecord, result[-1].decision_id),), write=False)
            return result

    def record(self, request, proposal, *, actor_id, invocation_id, recorded_at, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            invocation = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if (invocation is None or invocation.tool_id != REVIEW_LINK_TOOL or invocation.status != "running"
                    or invocation.input_payload.get("confirmed_by_user") is not True
                    or any(invocation.input_payload.get(key) != value for key, value in request.model_dump().items())):
                raise ImageRevisionIntegrityError("link review requires an exact confirmed canonical command")
            if invocation.conversation_id:
                conversation = session.get(ConversationRecord, invocation.conversation_id)
                if conversation is None or conversation.project_id != request.project_id:
                    raise ImageRevisionIntegrityError("link review conversation scope mismatch")
            goal_id = invocation.input_payload.get("agent_goal_id")
            if goal_id:
                goal = session.get(AgentGoalRecord, goal_id)
                if goal is None or goal.project_id != request.project_id or goal.conversation_id != invocation.conversation_id:
                    raise ImageRevisionIntegrityError("link review goal scope mismatch")
            row = session.get(ReferenceProposalRecord, request.proposal_id)
            if row is None or row.project_id != request.project_id or ReferenceLinkRepository._stored(session, row) != proposal:
                raise ImageRevisionIntegrityError("review proposal changed")
            assertion = proposal.proposal.assertions[proposal.assertion_ids.index(request.assertion_id)]
            history = self._history(session, request.project_id, request.proposal_id, request.assertion_id)
            replay = session.scalar(select(LinkDecisionRecord).where(LinkDecisionRecord.invocation_id == invocation_id))
            if replay is not None:
                result = self._read(replay)
                if (result not in history or result.reviewer_actor != actor_id or result.decision != request.decision
                        or result.reason != request.reason or result.previous_decision_id != request.expected_previous_decision_id):
                    raise ImageRevisionIntegrityError("review invocation already bound to a different decision")
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "reference_review", (replay,), write=False)
                require_current()
                return result
            require_expected_decision(history[-1] if history else None, request.expected_previous_decision_id)
            if request.proposal_digest != proposal.digest or request.evidence_digest != assertion_evidence_digest(assertion):
                raise ImageRevisionIntegrityError("review pins differ from the assertion")
            result = LinkDecision(str(uuid4()), request.project_id, request.proposal_id, request.assertion_id,
                proposal.proposal.image_revision_id, proposal.digest, snapshot_digest(asdict(assertion)),
                assertion_evidence_digest(assertion), request.decision, actor_id, request.reason, recorded_at,
                invocation_id, request.expected_previous_decision_id, len(history) + 1)
            session.add(LinkDecisionRecord(**{key: getattr(result, key) for key in (
                "decision_id", "project_id", "proposal_id", "assertion_id", "previous_decision_id", "sequence", "invocation_id")},
                payload=asdict(result), content_hash=result.digest))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.link.reviewed",
                occurred_at=recorded_at, correlation_id=request.project_id, entity_type="image_link_decision",
                entity_id=result.decision_id, entity_version=0, mutation_kind="append",
                patch={"project_id": request.project_id, "proposal_id": request.proposal_id,
                       "assertion_id": request.assertion_id, "decision_id": result.decision_id},
                query_keys=[["system-image-link-reviews", request.project_id, request.proposal_id, request.assertion_id]]), session=session)
            session.flush()
            require_current()
            return result
