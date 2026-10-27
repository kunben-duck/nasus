from __future__ import annotations

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, conint, field_serializer, model_validator
from ...domain.system_image.image_revision import ImageObjectMember, member_payload
from ...domain.system_image.link_recall import LINK_RECALL_METHOD
from .screened_link_candidates import SCREENED_RECALL_METHOD
from ...domain.system_image.source_context_roots import SourceContextRoot, SourceContextRootInventory


class ImageQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: StrictStr = Field(min_length=1, max_length=128)


class ImageListInput(ImageQueryInput):
    after_id: StrictStr = Field(default="", max_length=64)
    limit: conint(strict=True, ge=1, le=100) = 20


class ImagePageInput(ImageQueryInput):
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    section: Literal["objects", "relationships", "members", "source_members", "assertion_members", "semantic_assertion_members"] = "objects"
    offset: conint(strict=True, ge=0, le=100000) = 0
    limit: conint(strict=True, ge=1, le=100) = 25


class ImageEvidenceInput(ImageQueryInput):
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    object_id: StrictStr = Field(min_length=1, max_length=256)
    evidence_id: StrictStr = Field(min_length=1, max_length=128)
    start_line: Optional[conint(strict=True, ge=1)] = None
    max_lines: conint(strict=True, ge=1, le=200) = 100


class ImageDocumentInput(ImageQueryInput):
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    object_id: StrictStr = Field(min_length=1, max_length=256)
    offset: conint(strict=True, ge=0, le=90) = 0
    limit: conint(strict=True, ge=1, le=90) = 20


class ImageCodeIdentityInput(ImageQueryInput):
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    object_id: StrictStr = Field(min_length=1, max_length=256)


class ImageCodeDeltaInput(ImageQueryInput):
    before_image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    before_image_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    after_image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    after_image_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    kind: Optional[Literal["added_member", "removed_member", "revision_changed", "projection_changed", "unchanged"]] = None
    offset: conint(strict=True, ge=0, le=100000) = 0
    limit: conint(strict=True, ge=1, le=100) = 20


class ImageReferenceInput(ImageQueryInput):
    proposal_id: StrictStr = Field(min_length=1, max_length=128)
    section: Literal["assertions", "gaps"] = "assertions"
    offset: conint(strict=True, ge=0, le=10000) = 0
    limit: conint(strict=True, ge=1, le=50) = 20


class ImageDecisionInput(ImageQueryInput):
    proposal_id: StrictStr = Field(min_length=1, max_length=128)
    assertion_id: StrictStr = Field(min_length=1, max_length=128)
    through_decision_id: Optional[StrictStr] = Field(default=None, max_length=128)
    offset: conint(strict=True, ge=0, le=1000) = 0
    limit: conint(strict=True, ge=1, le=50) = 20


class ImageLinkCandidatesInput(ImageQueryInput):
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    target_object_id: StrictStr = Field(min_length=1, max_length=256)
    relation: Literal["implements", "asserts"]
    limit: conint(strict=True, ge=1, le=100) = 30
    method_version: Literal[LINK_RECALL_METHOD] = LINK_RECALL_METHOD


class ImageScreenedCandidatesInput(ImageLinkCandidatesInput):
    method_version: Literal[SCREENED_RECALL_METHOD] = SCREENED_RECALL_METHOD


class ImageSemanticDecisionInput(ImageQueryInput):
    evaluation_id: StrictStr = Field(min_length=1, max_length=128)
    subject_object_id: StrictStr = Field(min_length=1, max_length=128)
    through_decision_id: Optional[StrictStr] = Field(default=None, max_length=128)
    offset: conint(strict=True, ge=0, le=1000) = 0
    limit: conint(strict=True, ge=1, le=50) = 20


class ImageSemanticApplicabilityInput(ImageQueryInput):
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    expected_image_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_decision_id: StrictStr = Field(min_length=1, max_length=128)
    subject_object_id: StrictStr = Field(min_length=1, max_length=128)
    target_object_id: StrictStr = Field(min_length=1, max_length=128)
    through_decision_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)


class ImageSourceDeltaInput(ImageQueryInput):
    before_revision_id: StrictStr = Field(min_length=1, max_length=128)
    after_revision_id: StrictStr = Field(min_length=1, max_length=128)
    section: Literal["files", "rename_candidates"] = "files"
    kind: Optional[Literal["added", "modified", "deleted", "unchanged", "unresolved"]] = None
    offset: conint(strict=True, ge=0, le=100000) = 0
    limit: conint(strict=True, ge=1, le=100) = 50

    @model_validator(mode="after")
    def validate_filter(self):
        if self.section != "files" and self.kind is not None:
            raise ValueError("file kind filters do not apply to rename candidates")
        return self


class ImageContextImpactInput(ImageQueryInput):
    context_id: StrictStr = Field(min_length=1, max_length=128)
    context_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before_revision_id: StrictStr = Field(min_length=1, max_length=128)
    after_revision_id: StrictStr = Field(min_length=1, max_length=128)


class SourceContextRootsInput(ImageQueryInput):
    before_revision_id: StrictStr = Field(min_length=1, max_length=128)
    after_revision_id: StrictStr = Field(min_length=1, max_length=128)
    after_id: StrictStr = Field(default="", max_length=128)
    limit: conint(strict=True, ge=1, le=50) = 20


ImageQueryRequest = Union[ImageListInput, ImagePageInput, ImageEvidenceInput, ImageDocumentInput, ImageReferenceInput, ImageDecisionInput, ImageScreenedCandidatesInput, ImageLinkCandidatesInput, ImageSemanticDecisionInput, ImageSemanticApplicabilityInput, ImageSourceDeltaInput, ImageContextImpactInput, SourceContextRootsInput, ImageCodeIdentityInput, ImageCodeDeltaInput]


class ImageReceipt(BaseModel):
    """Persist opaque handles and a digest, not knowledge or source content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["nasus.image-query.v1"] = "nasus.image-query.v1"
    result_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ImageListReceipt(ImageReceipt):
    operation: Literal["list"] = "list"
    request: ImageListInput
    revision_ids: List[StrictStr] = Field(max_length=100)
    next_after_id: Optional[str]


class ImageCodeIdentityReceipt(ImageReceipt):
    operation: Literal["code_identity"] = "code_identity"
    request: ImageCodeIdentityInput
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    frozen_object_id: StrictStr = Field(min_length=1, max_length=256)
    canonical_object_id: StrictStr = Field(min_length=1, max_length=256)
    entity_id: StrictStr = Field(min_length=1, max_length=128)
    entity_revision_id: StrictStr = Field(min_length=1, max_length=128)
    source_revision_id: StrictStr = Field(min_length=1, max_length=128)
    alias_registration_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ImagePageReceipt(ImageReceipt):
    operation: Literal["read"] = "read"
    request: ImagePageInput
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    item_ids: List[StrictStr] = Field(max_length=100)
    frozen_members: List[ImageObjectMember] = Field(default_factory=list, max_length=100)
    total: conint(strict=True, ge=0)
    next_offset: Optional[conint(strict=True, ge=0)]
    publication: Literal["blocked_pending_revision_governance"] = "blocked_pending_revision_governance"

    @field_serializer("frozen_members")
    def serialize_frozen_members(self, members):
        return [member_payload(member) for member in members]


class ImageEvidenceReceipt(ImageReceipt):
    operation: Literal["evidence"] = "evidence"
    request: ImageEvidenceInput
    source_revision_id: str
    start_line: conint(strict=True, ge=1)
    end_line: conint(strict=True, ge=1)
    next_start_line: Optional[conint(strict=True, ge=1)]


class ImageDocumentReceipt(ImageReceipt):
    operation: Literal["document"] = "document"
    request: ImageDocumentInput
    document_revision_id: StrictStr
    source_revision_id: StrictStr
    payload_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_ids: List[StrictStr] = Field(max_length=100)
    total_fields: conint(strict=True, ge=0, le=90)
    next_offset: Optional[conint(strict=True, ge=0, le=90)]


class ImageReferenceReceipt(ImageReceipt):
    operation: Literal["references"] = "references"
    request: ImageReferenceInput
    image_revision_id: StrictStr
    proposal_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assertion_ids: List[StrictStr] = Field(max_length=50)
    next_offset: Optional[conint(strict=True, ge=0, le=10000)]


class ImageDecisionReceipt(ImageReceipt):
    operation: Literal["link_decisions"] = "link_decisions"
    request: ImageDecisionInput
    image_revision_id: StrictStr
    proposal_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    head_decision_id: Optional[StrictStr]
    decision_ids: List[StrictStr] = Field(max_length=50)
    next_offset: Optional[conint(strict=True, ge=0, le=1000)]


class ImageSemanticDecisionReceipt(ImageReceipt):
    operation: Literal["semantic_decisions"] = "semantic_decisions"
    request: ImageSemanticDecisionInput
    image_revision_id: StrictStr
    image_artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evaluation_artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assertion_id: StrictStr
    assertion_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    claim_id: StrictStr
    head_decision_id: Optional[StrictStr]
    decision_ids: List[StrictStr] = Field(max_length=50)
    total: conint(strict=True, ge=0, le=1000)
    next_offset: Optional[conint(strict=True, ge=0, le=1000)]


class LinkCandidatePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_id: StrictStr
    revision_id: StrictStr
    source_revision_id: StrictStr
    kind: Literal["code_entity", "test_case", "acceptance_criterion", "business_rule"]
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_ids: List[StrictStr] = Field(min_length=1, max_length=100)


class ImageLinkCandidatesReceipt(ImageReceipt):
    operation: Literal["link_candidates"] = "link_candidates"
    request: ImageLinkCandidatesInput
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target: LinkCandidatePin
    candidates: List[LinkCandidatePin] = Field(max_length=100)
    truncated: bool
    semantic_status: Literal["retrieved_not_asserted"] = "retrieved_not_asserted"


class ReviewHeadPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    subject_object_id: StrictStr = Field(min_length=1, max_length=128)
    head_decision_id: StrictStr = Field(min_length=1, max_length=128)
    head_decision_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ImageScreenedCandidatesReceipt(ImageLinkCandidatesReceipt):
    operation: Literal["screened_link_candidates"] = "screened_link_candidates"
    request: ImageScreenedCandidatesInput
    review_heads: List[ReviewHeadPin] = Field(max_length=64)
    review_scope_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    excluded_by_review: conint(strict=True, ge=0, le=64)
    review_scope: Literal["pinned_query_heads_not_live"] = "pinned_query_heads_not_live"


class ImageSemanticApplicabilityReceipt(ImageReceipt):
    operation: Literal["semantic_applicability"] = "semantic_applicability"
    request: ImageSemanticApplicabilityInput
    head_decision_id: StrictStr
    head_decision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_image_revision_id: StrictStr
    source_image_artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assertion_id: StrictStr
    assertion_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assessment_status: Literal["different_endpoints", "identity_unresolved", "stale_requires_review", "rejected_same_revisions", "same_revisions_review_required"]
    candidate_action: Literal["resolve_identity_before_transfer", "revalidate_before_review", "exclude_from_unreviewed_candidates", "review_before_acceptance"]
    approval_transferred: Literal[False] = False
    history_scope: Literal["pinned_claim_head_not_global_latest"] = "pinned_claim_head_not_global_latest"


class ImageSourceDeltaReceipt(ImageReceipt):
    operation: Literal["source_delta"] = "source_delta"
    request: ImageSourceDeltaInput
    delta_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before_manifest_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    after_manifest_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    counts: dict[Literal["added", "modified", "deleted", "unchanged", "unresolved"], conint(strict=True, ge=0, le=100000)]
    complete: StrictBool
    full_validation_required: StrictBool
    rename_candidate_count: conint(strict=True, ge=0, le=50000)
    total: conint(strict=True, ge=0, le=100000)
    next_offset: Optional[conint(strict=True, ge=0, le=100000)]
    integrity: Literal["verified_manifests"] = "verified_manifests"
    file_bodies_verified: Literal[False] = False
    impact_complete: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_counts(self):
        if set(self.counts) != {"added", "modified", "deleted", "unchanged", "unresolved"}:
            raise ValueError("source delta requires every presence category")
        return self


class ImageCodeDeltaReceipt(ImageReceipt):
    operation: Literal["code_member_delta"] = "code_member_delta"
    request: ImageCodeDeltaInput
    delta_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    counts: dict[Literal["added_member", "removed_member", "revision_changed", "projection_changed", "unchanged"], conint(strict=True, ge=0, le=100000)]
    source_scope_changed: StrictBool
    total: conint(strict=True, ge=0, le=100000)
    next_offset: Optional[conint(strict=True, ge=0, le=100000)]
    comparison_scope: Literal["registered_members_of_two_frozen_images"] = "registered_members_of_two_frozen_images"
    source_deletions_verified: Literal[False] = False
    rename_lineage_transferred: Literal[False] = False
    impact_complete: Literal[False] = False
    approval_transferred: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_inventory(self):
        from ...domain.system_image.code_member_delta import CODE_MEMBER_DELTA_KINDS
        if (set(self.counts) != CODE_MEMBER_DELTA_KINDS or sum(self.counts.values()) > 100000
                or self.total != (self.counts[self.request.kind] if self.request.kind else sum(self.counts.values()))
                or self.request.offset > self.total):
            raise ValueError("Code delta requires every fixed member category.")
        expected_next = min(self.request.offset + self.request.limit, self.total)
        if self.next_offset != (expected_next if expected_next < self.total else None):
            raise ValueError("Code delta pagination differs from its fixed inventory.")
        return self


class QualityDependencyPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["scope", "generation", "mapping"]
    artifact_id: StrictStr = Field(min_length=1, max_length=128)


class ImageContextImpactReceipt(ImageReceipt):
    operation: Literal["context_change_impact"] = "context_change_impact"
    request: ImageContextImpactInput
    dependency_pins: List[QualityDependencyPin] = Field(max_length=127)
    graph_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    delta_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    query_scope_fingerprint: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dependency_count: conint(strict=True, ge=1, le=128)
    affected_count: conint(strict=True, ge=0, le=128)
    dependency_closure_complete: Literal[True] = True
    prospective_only: Literal[True] = True
    impact_complete: Literal[False] = False
    invalidation_applied: Literal[False] = False
    generation_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_dependencies(self):
        keys = [(pin.kind, pin.artifact_id) for pin in self.dependency_pins]
        if keys != sorted(set(keys)) or self.affected_count > self.dependency_count:
            raise ValueError("invalid context impact dependency pins or counts")
        return self


class SourceContextRootPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    context_id: StrictStr = Field(min_length=1, max_length=128)
    context_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def to_domain(self):
        return SourceContextRoot(**self.model_dump())


class SourceContextRootsReceipt(ImageReceipt):
    operation: Literal["source_context_roots"] = "source_context_roots"
    request: SourceContextRootsInput
    roots: List[SourceContextRootPin] = Field(max_length=50)
    total: conint(strict=True, ge=0)
    next_after_id: Optional[StrictStr] = Field(max_length=128)
    delta_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before_manifest_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    after_manifest_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_scope_fingerprint: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    discovery_scope: Literal["authorized_archived_context_roots_at_observation"] = "authorized_archived_context_roots_at_observation"
    page_evidence_verified: Literal[True] = True
    downstream_dependency_graphs_verified: Literal[False] = False
    impact_complete: Literal[False] = False
    invalidation_applied: Literal[False] = False
    generation_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_root_pins(self):
        SourceContextRootInventory(tuple(root.to_domain() for root in self.roots), self.total, self.next_after_id).validate(
            self.request.after_id, self.request.limit)
        return self


ImageQueryReceipt = Union[ImageListReceipt, ImagePageReceipt, ImageEvidenceReceipt, ImageDocumentReceipt, ImageReferenceReceipt, ImageDecisionReceipt, ImageScreenedCandidatesReceipt, ImageLinkCandidatesReceipt, ImageSemanticDecisionReceipt, ImageSemanticApplicabilityReceipt, ImageSourceDeltaReceipt, ImageContextImpactReceipt, SourceContextRootsReceipt, ImageCodeIdentityReceipt, ImageCodeDeltaReceipt]
