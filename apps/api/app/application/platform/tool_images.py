from __future__ import annotations

from typing import Optional

from ..system_image.image_query_tools import ImageQueryToolPort, ImageQueryObservation
from ..system_image.image_query_models import ImageScreenedCandidatesReceipt
from .errors import PlatformApplicationError
from .tool_evidence import ToolEvidenceInvocationPort
from .tool_handlers.evidence import EvidenceToolAccessPort
from .tool_handlers.image_queries import IMAGE_QUERY_INPUTS
from .tool_handlers.query_input import query_payload


class ToolImageObservationApplicationService:
    def __init__(self, invocations: ToolEvidenceInvocationPort, images: ImageQueryToolPort, access: EvidenceToolAccessPort):
        self.invocations, self.images, self.access = invocations, images, access

    def _receipt(self, invocation_id: str, project_id: Optional[str] = None):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in IMAGE_QUERY_INPUTS:
            raise PlatformApplicationError("image_query_required", "A completed image query is required.", 409)
        self.access.require_invocation_project_scope(invocation)
        receipt = invocation.result.image_query if invocation.result else None
        if invocation.status != "completed" or receipt is None:
            raise PlatformApplicationError("image_query_required", "A completed image query is required.", 409)
        expected = IMAGE_QUERY_INPUTS[invocation.tool_id].model_validate(query_payload(invocation.input_payload))
        if type(receipt.request) is not type(expected) or receipt.request != expected:
            raise PlatformApplicationError("image_receipt_mismatch", "Image receipt does not match its invocation.", 409)
        if project_id is not None and expected.project_id != project_id:
            raise PlatformApplicationError("image_project_mismatch", "Image query belongs to another project.", 403)
        return invocation, receipt

    def describe(self, invocation_id: str, project_id: str) -> dict | None:
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in IMAGE_QUERY_INPUTS:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        invocation, receipt = self._receipt(invocation_id, project_id)
        self.images.expand(receipt)
        self.access.require_invocation_project_scope(invocation)
        # No raw source or object content goes to the planner implicitly.
        return receipt.model_dump(mode="json")

    def expand(self, invocation_id: str) -> ImageQueryObservation:
        invocation, receipt = self._receipt(invocation_id)
        result = self.images.expand(receipt)
        self.access.require_invocation_project_scope(invocation)
        return result

    def semantic_recall(self, project_id: str, invocation_id: str, *, verify_result: bool) -> ImageScreenedCandidatesReceipt:
        invocation, receipt = self._receipt(invocation_id, project_id)
        if not isinstance(receipt, ImageScreenedCandidatesReceipt):
            raise PlatformApplicationError("screened_recall_required", "A completed screened recall is required.", 409)
        if verify_result:
            self.images.expand(receipt)
        # Archived evaluations bind this entire receipt in their immutable input
        # digest. Do not recursively expand the evaluations behind review heads.
        self.access.require_invocation_project_scope(invocation)
        return receipt
