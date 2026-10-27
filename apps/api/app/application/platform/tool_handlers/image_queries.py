from __future__ import annotations

import asyncio

from ....domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ....domain.system_image.source_delta import SourceDeltaIntegrityError, SourceDeltaPageTooLarge, SourceDeltaUnavailable
from ....domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationImpactTooLarge
from ....domain.system_image.code_alias import AmbiguousCodeObjectAlias
from ...system_image.image_query_models import (
    ImageListInput, ImagePageInput, ImageEvidenceInput, ImageDocumentInput,
    ImageListReceipt, ImagePageReceipt, ImageDocumentReceipt,
    ImageReferenceInput, ImageReferenceReceipt,
    ImageDecisionInput, ImageDecisionReceipt,
    ImageLinkCandidatesInput, ImageLinkCandidatesReceipt,
    ImageSemanticDecisionInput, ImageSemanticDecisionReceipt,
    ImageSemanticApplicabilityInput, ImageSemanticApplicabilityReceipt,
    ImageScreenedCandidatesInput, ImageScreenedCandidatesReceipt,
    ImageSourceDeltaInput, ImageSourceDeltaReceipt,
    ImageContextImpactInput, ImageContextImpactReceipt,
    SourceContextRootsInput, SourceContextRootsReceipt,
    ImageCodeIdentityInput, ImageCodeIdentityReceipt,
    ImageCodeDeltaInput, ImageCodeDeltaReceipt,
)
from ...system_image.image_query_tools import ImageQueryToolPort
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort, EvidenceToolHandler
from .query_input import query_payload


IMAGE_QUERY_INPUTS = {
    "query.system_image.revisions.code_delta": ImageCodeDeltaInput,
    "query.system_image.revisions.resolve_code_object": ImageCodeIdentityInput,
    "query.system_image.sources.context_roots": SourceContextRootsInput,
    "query.system_image.context.change_impact": ImageContextImpactInput,
    "query.system_image.sources.delta": ImageSourceDeltaInput,
    "query.system_image.revisions.list": ImageListInput,
    "query.system_image.revisions.read": ImagePageInput,
    "query.system_image.revisions.evidence": ImageEvidenceInput,
    "query.system_image.revisions.document": ImageDocumentInput,
    "query.system_image.references.read": ImageReferenceInput,
    "query.system_image.links.decisions": ImageDecisionInput,
    "query.system_image.links.candidates": ImageLinkCandidatesInput,
    "query.system_image.links.screened_candidates": ImageScreenedCandidatesInput,
    "query.system_image.links.semantic_decisions": ImageSemanticDecisionInput,
    "query.system_image.links.decision_applicability": ImageSemanticApplicabilityInput,
}


class ImageQueryToolHandler:
    def __init__(self, images: ImageQueryToolPort, events: ToolStatusEventPort, access: EvidenceToolAccessPort) -> None:
        self.images, self.events, self.access = images, events, access

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.events.emit_tool_status(invocation.id, "running", "Checking frozen image revision", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = IMAGE_QUERY_INPUTS[invocation.tool_id].model_validate(query_payload(invocation.input_payload))
            receipt = await asyncio.to_thread(self.images.execute, request)
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            if isinstance(exc, (SourceAccessDenied, StaleSourceAccessScope)):
                summary = "Image input access was denied or changed; reload the revision."
            elif isinstance(exc, AmbiguousCodeObjectAlias):
                summary = "Code reference is ambiguous in this image; select an exact frozen member."
            elif isinstance(exc, DerivationImpactIntegrityError):
                summary = "Context change impact failed dependency integrity verification."
            elif isinstance(exc, DerivationImpactTooLarge):
                summary = "Complete context dependency closure exceeds the query budget; no partial impact was returned."
            elif isinstance(exc, SourceDeltaIntegrityError):
                summary = "Source delta failed integrity verification."
            elif isinstance(exc, SourceDeltaUnavailable):
                summary = "Source delta archive is temporarily unavailable."
            elif isinstance(exc, SourceDeltaPageTooLarge):
                summary = "Source delta page exceeds the query limit; request fewer items."
            elif isinstance(exc, ImageRevisionIntegrityError):
                summary = "Image revision failed integrity verification."
            elif isinstance(exc, ImageArtifactUnavailable):
                summary = "Image revision is temporarily unavailable."
            elif isinstance(exc, ImageRevisionPageTooLarge):
                summary = "Image page exceeds the query limit; request fewer items."
            else:
                summary = EvidenceToolHandler._failure_summary(exc).replace("source evidence", "image query").replace("Source evidence", "Image query")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary,
            ))
            return
        summary = "Frozen image query verified; candidate observations are not approved business assertions."
        next_tools = []
        if isinstance(receipt, ImageCodeDeltaReceipt):
            summary = "Registered code members compared at two fixed images. Removed membership is not proven source deletion; no rename lineage, approval or coverage was transferred."
            next_tools.append("query.system_image.revisions.read")
            if receipt.next_offset is not None:
                next_tools.append("query.system_image.revisions.code_delta")
        elif isinstance(receipt, ImageCodeIdentityReceipt):
            summary = "Code identity resolved at a fixed image and source revision. Historical membership and approvals are unchanged."
            next_tools.append("query.system_image.revisions.read")
        elif isinstance(receipt, SourceContextRootsReceipt):
            summary = "Archived context roots verified across this project's images at the pinned old source revision. Discovery does not verify downstream graphs, invalidate history, approve coverage or authorize execution."
            if receipt.roots:
                next_tools.append("query.system_image.context.change_impact")
            if receipt.next_after_id:
                next_tools.append("query.system_image.sources.context_roots")
        elif isinstance(receipt, ImageContextImpactReceipt):
            summary = "Prospective context dependency impact verified. No historical artifact, approval or coverage was changed; this is not complete business impact or execution consent."
        elif isinstance(receipt, ImageSourceDeltaReceipt):
            summary = "Pinned source manifests compared. This is not complete change impact, entity lineage, approval or publication."
            if receipt.next_offset is not None:
                next_tools.append("query.system_image.sources.delta")
        elif isinstance(receipt, ImageListReceipt):
            if receipt.revision_ids:
                next_tools.append("query.system_image.revisions.read")
            if receipt.next_after_id:
                next_tools.append("query.system_image.revisions.list")
        elif isinstance(receipt, ImagePageReceipt):
            if receipt.next_offset is not None or (receipt.item_ids and receipt.request.section != "members"):
                next_tools.append("query.system_image.revisions.read")
            if any(member.evidence_ids for member in receipt.frozen_members):
                next_tools.append("query.system_image.revisions.evidence")
            if any(member.kind == "source_document" for member in receipt.frozen_members):
                next_tools.append("query.system_image.revisions.document")
        elif isinstance(receipt, ImageScreenedCandidatesReceipt):
            next_tools.extend(["query.system_image.revisions.document", "query.system_image.revisions.evidence"])
            summary = "Candidates filtered before limiting against fixed review heads. Historical replay is not current eligibility; model evaluation rechecks current decisions. No approval or coverage was transferred."
        elif isinstance(receipt, ImageLinkCandidatesReceipt):
            next_tools.extend(["query.system_image.revisions.document", "query.system_image.revisions.evidence"])
            summary = "Related endpoints retrieved for semantic investigation; no implementation, oracle approval or coverage was established."
        elif isinstance(receipt, ImageDocumentReceipt):
            if receipt.next_offset is not None:
                next_tools.append("query.system_image.revisions.document")
            if receipt.evidence_ids:
                next_tools.append("query.system_image.revisions.evidence")
        elif isinstance(receipt, ImageSemanticApplicabilityReceipt):
            summary = "Decision applicability verified against pinned endpoints and history; no approval was transferred and no image was published."
        elif isinstance(receipt, ImageSemanticDecisionReceipt):
            summary = "Semantic review history verified at a fixed head; decisions do not approve an oracle, establish coverage or publish an image."
            if receipt.next_offset is not None:
                next_tools.append("query.system_image.links.semantic_decisions")
            if receipt.head_decision_id:
                next_tools.append("query.system_image.links.decision_applicability")
        elif isinstance(receipt, ImageDecisionReceipt):
            if receipt.next_offset is not None:
                next_tools.append("query.system_image.links.decisions")
        elif isinstance(receipt, ImageReferenceReceipt):
            if receipt.next_offset is not None:
                next_tools.append("query.system_image.references.read")
            next_tools.append("query.system_image.revisions.evidence")
        elif receipt.next_start_line is not None:
            next_tools.append("query.system_image.revisions.evidence")
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary, image_query=receipt,
            next_recommended_tools=next_tools,
        ))
