from __future__ import annotations

from dataclasses import asdict, fields
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.reference_links import PROPOSE_REFERENCES_TOOL, StoredReferenceProposal
from ...domain.system_image.reference_links import REFERENCE_METHOD, ReferenceAssertion, ReferenceGap, ReferenceProposal
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from .db_models import AgentGoalRecord, ConversationRecord, ToolInvocationRecord
from .image_revision_models import ImageObjectMemberRecord, ImageRevisionRecord
from .reference_link_models import ReferenceProposalRecord, ReferenceAssertionRecord, ReferenceProposalInvocationRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope


class ReferenceLinkRepository:
    @staticmethod
    def _stored(session, row):
        image = session.get(ImageRevisionRecord, row.image_revision_id)
        if image is None or image.project_id != row.project_id or image.artifact_hash != row.image_artifact_hash or row.method_version != REFERENCE_METHOD:
            raise ImageRevisionIntegrityError("reference proposal image scope mismatch")
        assertions = session.scalars(select(ReferenceAssertionRecord).where(
            ReferenceAssertionRecord.proposal_id == row.proposal_id).order_by(ReferenceAssertionRecord.ordinal)).all()
        values = []
        for i, saved in enumerate(assertions):
            if saved.ordinal != i or saved.project_id != row.project_id or saved.image_revision_id != row.image_revision_id:
                raise ImageRevisionIntegrityError("reference assertion scope mismatch")
            value = {field.name: getattr(saved, field.name) for field in fields(ReferenceAssertion)}
            for side in ("subject_evidence_ids", "object_evidence_ids"):
                value[side] = tuple(value[side])
            values.append(ReferenceAssertion(**value))
        proposal = ReferenceProposal(row.project_id, row.image_revision_id, row.image_artifact_hash, tuple(values),
            tuple(ReferenceGap(**{**gap, "evidence_ids": tuple(gap["evidence_ids"]),
                                  "candidate_object_ids": tuple(gap["candidate_object_ids"])}) for gap in row.gaps),
            row.document_count, row.method_version)
        if proposal.digest != row.content_hash:
            raise ImageRevisionIntegrityError("reference proposal digest mismatch")
        ReferenceLinkRepository._validate_members(session, proposal)
        return StoredReferenceProposal(row.proposal_id, row.content_hash, row.created_at, proposal,
                                       tuple(item.assertion_id for item in assertions))

    @staticmethod
    def _validate_members(session, proposal):
        members = {item.object_id: item for item in session.scalars(select(ImageObjectMemberRecord).where(
            ImageObjectMemberRecord.image_revision_id == proposal.image_revision_id,
            ImageObjectMemberRecord.project_id == proposal.project_id))}
        def require(ident, revision, evidence):
            member = members.get(ident)
            if (member is None or member.kind != "source_document" or member.document_revision_id != revision
                    or not evidence or not set(evidence).issubset(member.evidence_ids)):
                raise ImageRevisionIntegrityError("reference endpoint or evidence is outside the frozen image")
        if proposal.document_count != sum(item.kind == "source_document" for item in members.values()):
            raise ImageRevisionIntegrityError("reference derivation did not include all frozen documents")
        for assertion in proposal.assertions:
            require(assertion.subject_object_id, assertion.subject_revision_id, assertion.subject_evidence_ids)
            require(assertion.object_id, assertion.object_revision_id, assertion.object_evidence_ids)
        for gap in proposal.gaps:
            subject = members.get(gap.subject_object_id)
            if subject is None:
                raise ImageRevisionIntegrityError("reference gap subject is missing")
            require(subject.object_id, subject.document_revision_id, gap.evidence_ids)
            if any(ident not in members or members[ident].kind != "source_document" for ident in gap.candidate_object_ids):
                raise ImageRevisionIntegrityError("reference alternatives are outside the frozen image")

    @staticmethod
    def _invocation(session, proposal, invocation_id):
        invocation = session.get(ToolInvocationRecord, invocation_id)
        if (invocation is None or invocation.status != "running" or invocation.tool_id != PROPOSE_REFERENCES_TOOL
                or invocation.input_payload.get("project_id") != proposal.project_id
                or invocation.input_payload.get("image_revision_id") != proposal.image_revision_id):
            raise ImageRevisionIntegrityError("reference derivation requires a running canonical invocation")
        if invocation.conversation_id:
            conversation = session.get(ConversationRecord, invocation.conversation_id)
            if conversation is None or conversation.project_id != proposal.project_id:
                raise ImageRevisionIntegrityError("reference derivation conversation scope mismatch")
        goal_id = invocation.input_payload.get("agent_goal_id")
        if goal_id:
            goal = session.get(AgentGoalRecord, goal_id)
            if goal is None or goal.project_id != proposal.project_id or goal.conversation_id != invocation.conversation_id:
                raise ImageRevisionIntegrityError("reference derivation goal scope mismatch")

    def record(self, proposal, *, actor_id, invocation_id, created_at, require_current_scope):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, proposal.project_id)
            self._invocation(session, proposal, invocation_id)
            image = session.get(ImageRevisionRecord, proposal.image_revision_id)
            if image is None or image.project_id != proposal.project_id or image.artifact_hash != proposal.image_artifact_hash:
                raise ImageRevisionIntegrityError("reference derivation image scope mismatch")
            self._validate_members(session, proposal)
            row = session.scalar(select(ReferenceProposalRecord).where(
                ReferenceProposalRecord.project_id == proposal.project_id, ReferenceProposalRecord.content_hash == proposal.digest))
            reused = row is not None
            previous = session.get(ReferenceProposalInvocationRecord, invocation_id)
            if previous and (row is None or previous.proposal_id != row.proposal_id or previous.project_id != proposal.project_id):
                raise ImageRevisionIntegrityError("invocation is bound to a different reference proposal")
            if row is None:
                row = ReferenceProposalRecord(proposal_id=str(uuid4()), project_id=proposal.project_id,
                    image_revision_id=proposal.image_revision_id, image_artifact_hash=proposal.image_artifact_hash,
                    content_hash=proposal.digest, method_version=proposal.method_version, document_count=proposal.document_count,
                    gaps=[asdict(gap) for gap in proposal.gaps], created_at=created_at, created_by=actor_id)
                session.add(row)
                session.flush()
                for i, assertion in enumerate(proposal.assertions):
                    session.add(ReferenceAssertionRecord(assertion_id=str(uuid4()), project_id=proposal.project_id,
                        proposal_id=row.proposal_id, image_revision_id=proposal.image_revision_id, ordinal=i, **asdict(assertion)))
                session.flush()
            stored = self._stored(session, row)
            if stored.proposal != proposal:
                raise ImageRevisionIntegrityError("reference derivation digest collision")
            if reused:
                # Both committed replay and a new invocation reusing a fact
                # must verify it, even after its old Outbox events expire.
                from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
                RelationFactProvenanceProjectorV1().facts(session, "proposal", (row,), write=False)
            if previous is None:
                session.add(ReferenceProposalInvocationRecord(invocation_id=invocation_id, project_id=proposal.project_id,
                                                            proposal_id=row.proposal_id))
                EventOutboxRepository().append(EventPayload(event_id=str(uuid4()),
                    event_type="system_image.references.proposed", occurred_at=created_at, correlation_id=proposal.project_id,
                    entity_type="image_reference_proposal", entity_id=row.proposal_id, entity_version=0, mutation_kind="append",
                    patch={"project_id": proposal.project_id, "proposal_id": row.proposal_id},
                    query_keys=[["system-image-references", proposal.project_id, proposal.image_revision_id]]), session=session)
            session.flush()
            require_current_scope()
            return stored

    def get(self, project_id, proposal_id):
        with session_scope() as session:
            row = session.get(ReferenceProposalRecord, proposal_id)
            if row is None or row.project_id != project_id:
                raise KeyError("reference proposal not found")
            from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
            RelationFactProvenanceProjectorV1().facts(session, "proposal", (row,), write=False)
            return self._stored(session, row)

    def list_for_image(self, project_id, image_revision_id, after_id, limit):
        with session_scope() as session:
            rows = session.scalars(select(ReferenceProposalRecord).where(
                    ReferenceProposalRecord.project_id == project_id,
                    ReferenceProposalRecord.image_revision_id == image_revision_id,
                    ReferenceProposalRecord.proposal_id > after_id).order_by(ReferenceProposalRecord.proposal_id).limit(limit)).all()
            from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
            RelationFactProvenanceProjectorV1().facts(session, "proposal", rows, write=False)
            return tuple({"proposal_id": row.proposal_id, "digest": row.content_hash, "created_at": row.created_at} for row in rows)
