from dataclasses import asdict

from sqlalchemy import select

from ...application.system_image.image_membership import pin_assertion
from ...domain.system_image.image_membership import FREEZE_LINKS_TOOL, assertion_member
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.link_decisions import StaleLinkDecision
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord
from .image_revision_models import ImageRevisionRecord, ImageAssertionMemberRecord, ImageObjectMemberRecord
from .reference_link_models import ReferenceProposalRecord
from .reference_link_repository import ReferenceLinkRepository
from .link_decision_repository import LinkDecisionRepository


class ImageMembershipRepository:
    @staticmethod
    def read(session, project_id, image_revision_id):
        rows = session.scalars(select(ImageAssertionMemberRecord).where(
            ImageAssertionMemberRecord.project_id == project_id,
            ImageAssertionMemberRecord.image_revision_id == image_revision_id).order_by(ImageAssertionMemberRecord.assertion_id))
        result = []
        for row in rows:
            try:
                member = assertion_member(row.payload)
            except (KeyError, TypeError, ValueError) as exc:
                raise ImageRevisionIntegrityError("malformed persisted assertion membership") from exc
            if (row.content_hash != snapshot_digest(asdict(member)) or any(getattr(row, key) != getattr(member, key)
                    for key in ("assertion_id", "proposal_id", "decision_id", "origin_image_revision_id"))):
                raise ImageRevisionIntegrityError("persisted assertion membership mismatch")
            result.append(member)
        return tuple(result)

    @classmethod
    def validate_parent(cls, session, commit, manifest, baseline_id, members, relationship_count, tool_id):
        request = commit.request
        parent = session.get(ImageRevisionRecord, request.parent_revision_id)
        if (parent is None or parent.project_id != request.project_id or manifest.project_id != request.project_id
                or parent.manifest_id != manifest.manifest_id or parent.manifest_hash != manifest.content_hash
                or parent.baseline_id != baseline_id or parent.artifact_hash != request.parent_artifact_hash
                or parent.relationship_count != relationship_count):
            raise ImageRevisionIntegrityError("reviewed image parent mismatch")
        invocation = session.scalar(select(ToolInvocationRecord).where(
            ToolInvocationRecord.id == commit.invocation_id).with_for_update())
        if (invocation is None or invocation.tool_id != tool_id or invocation.status != "running"
                or invocation.input_payload.get("confirmed_by_user") is not True
                or any(invocation.input_payload.get(key) != value for key, value in request.model_dump(mode="json").items())):
            raise ImageRevisionIntegrityError("freeze requires an exact confirmed canonical command")
        if invocation.conversation_id:
            conversation = session.get(ConversationRecord, invocation.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ImageRevisionIntegrityError("freeze conversation scope mismatch")
        if invocation.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, invocation.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != invocation.conversation_id:
                raise ImageRevisionIntegrityError("freeze goal scope mismatch")
        parent_objects = session.scalars(select(ImageObjectMemberRecord).where(
            ImageObjectMemberRecord.project_id == request.project_id,
            ImageObjectMemberRecord.image_revision_id == parent.image_revision_id).order_by(ImageObjectMemberRecord.object_id)).all()
        if len(members) != len(parent_objects) or any(any(
                getattr(frozen, key) != (tuple(getattr(stored, key)) if key == "evidence_ids" else getattr(stored, key))
                for key in asdict(frozen)) for frozen, stored in zip(members, parent_objects)):
            raise ImageRevisionIntegrityError("reviewed candidate cannot change parent object members")
        return parent

    @classmethod
    def validate(cls, session, commit, manifest, baseline_id, members, relationship_count):
        request = commit.request
        parent = cls.validate_parent(session, commit, manifest, baseline_id, members, relationship_count, FREEZE_LINKS_TOOL)
        inherited = cls.read(session, request.project_id, parent.image_revision_id)
        if inherited != commit.inherited:
            raise ImageRevisionIntegrityError("inherited assertion membership mismatch")
        row = session.get(ReferenceProposalRecord, request.proposal_id)
        if row is None or row.project_id != request.project_id:
            raise ImageRevisionIntegrityError("freeze proposal scope mismatch")
        saved = ReferenceLinkRepository._stored(session, row)
        if saved.digest != request.proposal_digest:
            raise ImageRevisionIntegrityError("freeze proposal digest mismatch")
        if (len(commit.selected) != len(request.decision_ids)
                or {item.decision_id for item in commit.selected} != set(request.decision_ids)):
            raise ImageRevisionIntegrityError("freeze decision selection mismatch")
        for member in commit.selected:
            if (member.proposal_id != saved.proposal_id or member.assertion_id not in saved.assertion_ids
                    or (saved.proposal.image_revision_id != parent.image_revision_id
                        and member.assertion_id not in {item.assertion_id for item in inherited})):
                raise ImageRevisionIntegrityError("freeze assertion outside parent")
            history = LinkDecisionRepository._history(session, request.project_id, request.proposal_id, member.assertion_id)
            if not history or history[-1].decision_id != member.decision_id:
                raise StaleLinkDecision("review changed before freeze commit")
            if pin_assertion(saved, member.assertion_id, history[-1]) != member:
                raise ImageRevisionIntegrityError("freeze decision content mismatch")
        commit.require_current()
        merged = {item.assertion_id: item for item in inherited}
        merged.update({item.assertion_id: item for item in commit.selected})
        return tuple(merged[key] for key in sorted(merged))

    @staticmethod
    def attach(session, candidate, members):
        for item in members:
            session.add(ImageAssertionMemberRecord(image_revision_id=candidate.image_revision_id,
                project_id=candidate.project_id, **{key: getattr(item, key) for key in (
                    "assertion_id", "proposal_id", "decision_id", "origin_image_revision_id")},
                payload=asdict(item), content_hash=snapshot_digest(asdict(item))))
