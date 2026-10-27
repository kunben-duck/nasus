from dataclasses import asdict

from sqlalchemy import select

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, member_payload
from ...domain.system_image.link_decisions import StaleLinkDecision
from ...domain.system_image.semantic_membership import FREEZE_SEMANTIC_TOOL, semantic_member, validate_semantic_members
from ...domain.system_image.source_snapshots import snapshot_digest
from .image_revision_models import ImageRevisionRecord
from .image_membership_repository import ImageMembershipRepository
from .semantic_membership_models import ImageSemanticMemberRecord
from .semantic_review_models import SemanticAssertionRecord
from .semantic_review_repository import SemanticReviewRepository


class SemanticMembershipRepository:
    @staticmethod
    def read(session, project_id, image_revision_id):
        rows = session.scalars(select(ImageSemanticMemberRecord).where(
            ImageSemanticMemberRecord.project_id == project_id,
            ImageSemanticMemberRecord.image_revision_id == image_revision_id).order_by(ImageSemanticMemberRecord.claim_id))
        result = []
        for row in rows:
            try:
                value = semantic_member(row.payload)
            except (ValueError, TypeError, KeyError) as exc:
                raise ImageRevisionIntegrityError("malformed persisted semantic membership") from exc
            if (row.content_hash != snapshot_digest(asdict(value)) or row.claim_id != value.claim_id
                    or row.project_id != value.assertion.project_id or row.assertion_id != value.assertion.assertion_id
                    or row.decision_id != value.decision.decision_id):
                raise ImageRevisionIntegrityError("persisted semantic membership mismatch")
            result.append(value)
        return tuple(result)

    @staticmethod
    def _ancestors(session, parent):
        ancestors, current = {}, parent
        while current is not None:
            if len(ancestors) >= 1000 or current.image_revision_id in ancestors:
                raise ImageRevisionIntegrityError("invalid or oversized image ancestry")
            if (current.project_id, current.manifest_id, current.manifest_hash, current.baseline_id) != (
                    parent.project_id, parent.manifest_id, parent.manifest_hash, parent.baseline_id):
                raise ImageRevisionIntegrityError("review ancestry changed frozen inputs")
            ancestors[current.image_revision_id] = current.artifact_hash
            if current.parent_revision_id is None:
                break
            previous = session.get(ImageRevisionRecord, current.parent_revision_id)
            if previous is None or previous.artifact_hash != current.parent_artifact_hash:
                raise ImageRevisionIntegrityError("review ancestry lost its parent pin")
            current = previous
        return ancestors

    @classmethod
    def validate(cls, session, commit, manifest, baseline_id, members, relationship_count):
        request = commit.request
        parent = ImageMembershipRepository.validate_parent(session, commit, manifest, baseline_id,
            members, relationship_count, FREEZE_SEMANTIC_TOOL)
        inherited = cls.read(session, request.project_id, parent.image_revision_id)
        references = ImageMembershipRepository.read(session, request.project_id, parent.image_revision_id)
        if inherited != commit.inherited or references != commit.references:
            raise ImageRevisionIntegrityError("semantic freeze changed inherited members")
        if (len(commit.selected) != len(request.decision_ids)
                or {item.decision.decision_id for item in commit.selected} != set(request.decision_ids)
                or len({item.claim_id for item in commit.selected}) != len(commit.selected)):
            raise ImageRevisionIntegrityError("semantic freeze decision selection mismatch")
        ancestors = cls._ancestors(session, parent)
        for member in commit.selected:
            assertion, decision = member.assertion, member.decision
            if ancestors.get(assertion.image_revision_id) != assertion.image_artifact_hash:
                raise ImageRevisionIntegrityError("semantic decision is outside the unchanged parent lineage")
            row = session.get(SemanticAssertionRecord, assertion.assertion_id)
            if row is None or SemanticReviewRepository._assertion(row) != assertion:
                raise ImageRevisionIntegrityError("semantic freeze assertion changed")
            SemanticReviewRepository._frozen(session, assertion)
            history = SemanticReviewRepository._history(session, request.project_id, member.claim_id)
            if not history or history[-1] != decision:
                raise StaleLinkDecision("semantic decision changed before freeze commit")
        merged = {item.claim_id: item for item in inherited}
        merged.update({item.claim_id: item for item in commit.selected})
        result = tuple(merged[key] for key in sorted(merged))
        validate_semantic_members(result, [member_payload(item) for item in members], request.project_id)
        if len(result) + len(references) > 1000:
            raise ImageRevisionIntegrityError("combined assertion membership exceeds budget")
        commit.require_current()
        return references, result

    @staticmethod
    def attach(session, candidate, members):
        for item in members:
            session.add(ImageSemanticMemberRecord(image_revision_id=candidate.image_revision_id,
                project_id=candidate.project_id, claim_id=item.claim_id, assertion_id=item.assertion.assertion_id,
                decision_id=item.decision.decision_id, payload=asdict(item), content_hash=snapshot_digest(asdict(item))))
