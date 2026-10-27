from __future__ import annotations

from dataclasses import asdict
import json
from typing import Optional, Protocol, Union

from ...domain.system_image.image_revision import ImageObjectMember, ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.source_snapshots import snapshot_digest
from .evidence_queries import EvidencePage
from .document_queries import SourceDocumentPage
from .reference_links import ReferenceLinkApplicationService, ReferenceProposalPage
from .link_decisions import LinkDecisionApplicationService, LinkDecisionPage
from .link_candidates import LinkCandidateQueryApplicationService, LinkCandidatePage
from .semantic_review import SemanticReviewApplicationService, SemanticDecisionPage
from .semantic_applicability import SemanticApplicabilityApplicationService, SemanticDecisionApplicability
from .semantic_screening import SemanticScreeningApplicationService
from .screened_link_candidates import ScreenedLinkCandidateQueryApplicationService, ScreenedLinkCandidatePage
from .image_revision_queries import ImageRevisionList, ImageRevisionPage, ImageRevisionQueryApplicationService
from .source_deltas import SourceDeltaPage, SourceDeltaQueryApplicationService
from .context_change_impact import ContextChangeImpact, ContextChangeImpactApplicationService
from .source_context_roots import SourceContextRootsPage, SourceContextRootApplicationService
from .code_aliases import FrozenCodeObjectIdentity
from .code_member_deltas import CodeMemberDeltaApplicationService, CodeMemberDeltaPage
from ...domain.system_image.source_context_roots import SourceContextRootInventory
from .image_query_models import (
    ImageListInput, ImagePageInput, ImageEvidenceInput, ImageDocumentInput, ImageQueryRequest,
    ImageListReceipt, ImagePageReceipt, ImageEvidenceReceipt, ImageDocumentReceipt, ImageQueryReceipt,
    ImageReferenceInput, ImageReferenceReceipt,
    ImageDecisionInput, ImageDecisionReceipt,
    ImageLinkCandidatesInput, ImageLinkCandidatesReceipt, LinkCandidatePin,
    ImageSemanticDecisionInput, ImageSemanticDecisionReceipt,
    ImageSemanticApplicabilityInput, ImageSemanticApplicabilityReceipt,
    ImageScreenedCandidatesInput, ImageScreenedCandidatesReceipt, ReviewHeadPin,
    ImageSourceDeltaInput, ImageSourceDeltaReceipt,
    ImageContextImpactInput, ImageContextImpactReceipt, QualityDependencyPin,
    SourceContextRootsInput, SourceContextRootsReceipt, SourceContextRootPin,
    ImageCodeIdentityInput, ImageCodeIdentityReceipt,
    ImageCodeDeltaInput, ImageCodeDeltaReceipt,
)


ImageQueryObservation = Union[ImageRevisionList, ImageRevisionPage, EvidencePage, SourceDocumentPage, ReferenceProposalPage, LinkDecisionPage, ScreenedLinkCandidatePage, LinkCandidatePage, SemanticDecisionPage, SemanticDecisionApplicability, SourceDeltaPage, ContextChangeImpact, SourceContextRootsPage, FrozenCodeObjectIdentity, CodeMemberDeltaPage]


class ImageQueryToolPort(Protocol):
    def execute(self, request: ImageQueryRequest) -> ImageQueryReceipt: ...

    def execute_with_observation(self, request: ImageQueryRequest) -> tuple[ImageQueryReceipt, ImageQueryObservation]: ...

    def expand(self, receipt: ImageQueryReceipt) -> ImageQueryObservation: ...


class ImageQueryToolApplicationService:
    def __init__(self, queries: ImageRevisionQueryApplicationService, references: Optional[ReferenceLinkApplicationService] = None,
                 decisions: Optional[LinkDecisionApplicationService] = None,
                 semantic_reviews: Optional[SemanticReviewApplicationService] = None,
                 source_deltas: Optional[SourceDeltaQueryApplicationService] = None,
                 context_impacts: Optional[ContextChangeImpactApplicationService] = None,
                 source_context_roots: Optional[SourceContextRootApplicationService] = None) -> None:
        self.queries = queries
        self.references = references
        self.decisions = decisions
        self.semantic_reviews = semantic_reviews
        self.source_deltas = source_deltas
        self.context_impacts = context_impacts
        self.source_context_roots = source_context_roots
        self.semantic_applicability = SemanticApplicabilityApplicationService(queries, semantic_reviews) if semantic_reviews else None
        self.link_candidates = LinkCandidateQueryApplicationService(queries)
        self.screened_candidates = ScreenedLinkCandidateQueryApplicationService(queries,
            SemanticScreeningApplicationService(self.semantic_applicability, semantic_reviews.repository)) if semantic_reviews else None

    def execute(self, request: ImageQueryRequest) -> ImageQueryReceipt:
        return self.execute_with_observation(request)[0]

    def execute_with_observation(self, request: ImageQueryRequest) -> tuple[ImageQueryReceipt, ImageQueryObservation]:
        # A fresh authorized query already contains the exact observation that
        # produced its receipt. Replaying it immediately doubles source I/O.
        observation = self._read(request)
        receipt = self._receipt(request, observation)
        if len(json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")) > 65536:
            raise ImageRevisionPageTooLarge("Request fewer items; receipt exceeds 64 KiB.")
        return receipt, observation

    def expand(self, receipt: ImageQueryReceipt) -> ImageQueryObservation:
        if isinstance(receipt, ImageListReceipt):
            # Replay the selected revisions, not a mutable list/head query.
            scope = self.queries.authorization.scope(receipt.request.project_id)
            headers = tuple(self.queries.read(receipt.request.project_id, revision_id, section="members", limit=1).revision
                            for revision_id in receipt.revision_ids)
            self.queries.authorization.require_current(scope)
            result = ImageRevisionList(headers, receipt.next_after_id)
        elif isinstance(receipt, ImageCodeIdentityReceipt):
            result = self.queries.resolve_code_object(**receipt.request.model_dump(), registration_hash=receipt.alias_registration_hash)
        elif isinstance(receipt, SourceContextRootsReceipt):
            if self.source_context_roots is None:
                raise ValueError("reverse source dependencies are not configured")
            page = SourceContextRootInventory(tuple(root.to_domain() for root in receipt.roots), receipt.total, receipt.next_after_id)
            result = self.source_context_roots.read(**receipt.request.model_dump(), pinned=page,
                pinned_scope_fingerprint=receipt.source_scope_fingerprint)
        elif isinstance(receipt, ImageContextImpactReceipt):
            if self.context_impacts is None:
                raise ValueError("context impact is not configured")
            pins = tuple((pin.kind, pin.artifact_id) for pin in receipt.dependency_pins)
            result = self.context_impacts.read(**receipt.request.model_dump(), pinned=pins)
        elif isinstance(receipt, ImageScreenedCandidatesReceipt):
            if self.screened_candidates is None:
                raise ValueError("screened recall is not configured")
            pins = tuple((p.subject_object_id, p.head_decision_id, p.head_decision_digest) for p in receipt.review_heads)
            result = self.screened_candidates.read(**receipt.request.model_dump(), pinned_heads=pins)
        elif isinstance(receipt, (ImageDecisionReceipt, ImageSemanticDecisionReceipt, ImageSemanticApplicabilityReceipt)):
            # Empty string pins an empty history; None means a fresh head query.
            result = self._read(receipt.request.model_copy(update={"through_decision_id": receipt.head_decision_id or ""}))
        else:
            result = self._read(receipt.request)
        if self._receipt(receipt.request, result) != receipt:
            raise ImageRevisionIntegrityError("Image query receipt does not match its frozen result.")
        return result

    def _read(self, request: ImageQueryRequest) -> ImageQueryObservation:
        fields = request.model_dump()
        if isinstance(request, ImageCodeDeltaInput):
            return CodeMemberDeltaApplicationService(self.queries).read(**fields)
        if isinstance(request, ImageCodeIdentityInput):
            return self.queries.resolve_code_object(**fields)
        if isinstance(request, SourceContextRootsInput) and self.source_context_roots is not None:
            return self.source_context_roots.read(**fields)
        if isinstance(request, ImageContextImpactInput) and self.context_impacts is not None:
            return self.context_impacts.read(**fields)
        if isinstance(request, ImageSourceDeltaInput) and self.source_deltas is not None:
            before_id, after_id = fields.pop("before_revision_id"), fields.pop("after_revision_id")
            return self.source_deltas.read(before_id=before_id, after_id=after_id, **fields)
        if isinstance(request, ImageListInput):
            return self.queries.list(**fields)
        if isinstance(request, ImagePageInput):
            return self.queries.read(**fields)
        if isinstance(request, ImageEvidenceInput):
            return self.queries.read_evidence(**fields)
        if isinstance(request, ImageDocumentInput):
            page = self.queries.read_document(**fields)
            return SourceDocumentPage(**{**page, "fields": tuple(page["fields"]), "evidence": tuple(page["evidence"])})
        if isinstance(request, ImageReferenceInput) and self.references is not None:
            return self.references.read(**fields)
        if isinstance(request, ImageDecisionInput) and self.decisions is not None:
            return self.decisions.read(**fields)
        if isinstance(request, ImageSemanticDecisionInput) and self.semantic_reviews is not None:
            page = self.semantic_reviews.read(**fields)
            return SemanticDecisionPage(**{**page, "items": tuple(page["items"])})
        if isinstance(request, ImageSemanticApplicabilityInput) and self.semantic_applicability is not None:
            return self.semantic_applicability.read(**fields)
        if isinstance(request, ImageScreenedCandidatesInput):
            if self.screened_candidates is None:
                raise ValueError("screened recall is not configured")
            return self.screened_candidates.read(**fields)
        if isinstance(request, ImageLinkCandidatesInput):
            return self.link_candidates.read(**fields)
        raise ValueError("Unsupported image query.")

    @staticmethod
    def _receipt(request, result) -> ImageQueryReceipt:
        payload = asdict(result)
        # Additive header fields must not invalidate pre-v2 query receipts.
        headers = ([payload["revision"]] if isinstance(result, ImageRevisionPage) else
                   list(payload["items"]) if isinstance(result, ImageRevisionList) else [])
        for header in headers:
            if header["policy_version"] == "nasus.image-candidate.v1":
                for key in ("parent_revision_id", "parent_artifact_hash", "assertion_count"):
                    header.pop(key, None)
        digest = snapshot_digest(payload)
        if isinstance(request, ImageCodeDeltaInput):
            return ImageCodeDeltaReceipt(request=request, result_hash=digest, delta_hash=result.content_hash,
                counts=result.counts, source_scope_changed=result.source_scope_changed,
                total=result.total, next_offset=result.next_offset)
        if isinstance(request, ImageCodeIdentityInput):
            return ImageCodeIdentityReceipt(request=request, result_hash=digest, **{key: getattr(result, key) for key in
                ("image_artifact_hash", "frozen_object_id", "canonical_object_id", "entity_id", "entity_revision_id",
                 "source_revision_id", "alias_registration_hash")})
        if isinstance(request, SourceContextRootsInput):
            return SourceContextRootsReceipt(request=request, result_hash=digest,
                roots=[SourceContextRootPin(**asdict(root)) for root in result.inventory.items],
                total=result.inventory.total, next_after_id=result.inventory.next_after_id, delta_hash=result.delta_hash,
                before_manifest_hash=result.before.manifest_hash, after_manifest_hash=result.after.manifest_hash,
                source_scope_fingerprint=result.source_scope_fingerprint)
        if isinstance(request, ImageContextImpactInput):
            pins = sorted((node.kind, node.artifact_id) for node in result.dependencies
                          if node.kind in {"scope", "generation", "mapping"})
            return ImageContextImpactReceipt(request=request, result_hash=digest,
                dependency_pins=[QualityDependencyPin(kind=kind, artifact_id=ident) for kind, ident in pins],
                graph_hash=result.assessment.graph_hash, delta_hash=result.delta_hash,
                query_scope_fingerprint=result.assessment.query_scope_fingerprint,
                dependency_count=len(result.dependencies), affected_count=len(result.assessment.affected_keys))
        if isinstance(request, ImageSourceDeltaInput):
            return ImageSourceDeltaReceipt(request=request, result_hash=digest, delta_hash=result.content_hash,
                before_manifest_hash=result.before.manifest_hash, after_manifest_hash=result.after.manifest_hash,
                counts=result.counts, complete=result.complete, full_validation_required=result.full_validation_required,
                rename_candidate_count=result.rename_candidate_count, total=result.total, next_offset=result.next_offset)
        if isinstance(request, ImageSemanticApplicabilityInput):
            return ImageSemanticApplicabilityReceipt(request=request, result_hash=digest,
                assessment_status=result.assessment.status, candidate_action=result.assessment.candidate_action,
                **{key: getattr(result, key) for key in ("head_decision_id", "head_decision_digest", "source_image_revision_id",
                    "source_image_artifact_hash", "assertion_id", "assertion_digest")})
        if isinstance(request, ImageSemanticDecisionInput):
            assertion = result.assertion
            return ImageSemanticDecisionReceipt(request=request, result_hash=digest,
                **{key: assertion[key] for key in ("image_revision_id", "image_artifact_hash", "evaluation_artifact_hash",
                    "assertion_id", "assertion_digest", "evidence_digest", "claim_id")},
                head_decision_id=result.head_decision_id, decision_ids=[item["decision_id"] for item in result.items],
                total=result.total, next_offset=result.next_offset)
        if isinstance(request, ImageLinkCandidatesInput):
            def pin(endpoint):
                return LinkCandidatePin(**{key: value for key, value in asdict(endpoint).items() if key != "title"})
            if isinstance(request, ImageScreenedCandidatesInput):
                return ImageScreenedCandidatesReceipt(request=request, result_hash=digest, artifact_hash=result.image_artifact_hash,
                    target=pin(result.target), candidates=[pin(item.endpoint) for item in result.items], truncated=result.truncated,
                    review_heads=[ReviewHeadPin(subject_object_id=p.subject_object_id, head_decision_id=p.head_decision_id,
                        head_decision_digest=p.head_decision_digest) for p in result.review_screening],
                    review_scope_digest=result.review_scope_digest, excluded_by_review=result.excluded["historical_review"])
            return ImageLinkCandidatesReceipt(request=request, result_hash=digest, artifact_hash=result.image_artifact_hash,
                target=pin(result.target), candidates=[pin(item.endpoint) for item in result.items], truncated=result.truncated)
        if isinstance(request, ImageDecisionInput):
            return ImageDecisionReceipt(request=request, result_hash=digest, image_revision_id=result.image_revision_id,
                proposal_digest=result.proposal_digest, head_decision_id=result.head_decision_id,
                decision_ids=[item.decision_id for item in result.items], next_offset=result.next_offset)
        if isinstance(request, ImageReferenceInput):
            return ImageReferenceReceipt(request=request, result_hash=digest, image_revision_id=result.image_revision_id,
                proposal_digest=result.digest, assertion_ids=[item["assertion_id"] for item in result.items] if request.section == "assertions" else [],
                next_offset=result.next_offset)
        if isinstance(request, ImageListInput):
            return ImageListReceipt(request=request, result_hash=digest,
                                    revision_ids=[item.image_revision_id for item in result.items], next_after_id=result.next_after_id)
        if isinstance(request, ImagePageInput):
            key = {"objects": "id", "relationships": "id", "members": "object_id", "source_members": "binding_id", "assertion_members": "assertion_id", "semantic_assertion_members": "decision"}[request.section]
            item_ids = [item["decision"]["claim_id"] if request.section == "semantic_assertion_members" else item[key] for item in result.items]
            members = [ImageObjectMember(**{**item, "evidence_ids": tuple(item["evidence_ids"])}) for item in result.items] if request.section == "members" else []
            return ImagePageReceipt(request=request, result_hash=digest, artifact_hash=result.revision.artifact_hash,
                                    item_ids=item_ids, frozen_members=members,
                                    total=result.total, next_offset=result.next_offset)
        if isinstance(request, ImageDocumentInput):
            return ImageDocumentReceipt(request=request, result_hash=digest,
                document_revision_id=result.document["document_revision_id"],
                source_revision_id=result.document["source_revision_id"], payload_hash=result.payload_hash,
                evidence_ids=[item["evidence_id"] for item in result.evidence],
                total_fields=result.total_fields, next_offset=result.next_offset)
        return ImageEvidenceReceipt(request=request, result_hash=digest,
                                    source_revision_id=result.evidence.source_revision_id,
                                    start_line=result.start_line, end_line=result.end_line, next_start_line=result.next_start_line)
