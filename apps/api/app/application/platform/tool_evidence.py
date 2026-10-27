from __future__ import annotations

from typing import Protocol

from ..system_image.evidence_queries import EvidencePage
from ..system_image.evidence_tool_models import EvidenceReadReceipt
from ..system_image.evidence_tools import EvidenceToolPort
from .errors import PlatformApplicationError
from .tool_handlers.evidence import EvidenceToolAccessPort, READ_EVIDENCE_TOOL, LIST_EVIDENCE_TOOL
from .tool_models import ToolInvocation


class ToolEvidenceInvocationPort(Protocol):
    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation: ...


class ToolQueryObservationPort(Protocol):
    def describe(self, invocation_id: str, project_id: str) -> dict | None: ...


class ToolEvidenceObservationApplicationService:
    """Authorized, non-persisted source expansion for Agent and HTTP consumers."""

    def __init__(self, invocations: ToolEvidenceInvocationPort, evidence: EvidenceToolPort,
                 access: EvidenceToolAccessPort, images: ToolQueryObservationPort | None = None,
                 plans: ToolQueryObservationPort | None = None, acceptance: ToolQueryObservationPort | None = None,
                 contexts: ToolQueryObservationPort | None = None, publications: ToolQueryObservationPort | None = None,
                 indexes: ToolQueryObservationPort | None = None, test_design_scopes: ToolQueryObservationPort | None = None,
                 code_indexes: ToolQueryObservationPort | None = None,
                 investigations: ToolQueryObservationPort | None = None,
                 build_completions: ToolQueryObservationPort | None = None,
                 gap_ownership: ToolQueryObservationPort | None = None) -> None:
        self.invocations = invocations
        self.evidence = evidence
        self.access = access
        self.images = images
        self.plans = plans
        self.acceptance = acceptance
        self.contexts = contexts
        self.publications = publications
        self.indexes = indexes
        self.test_design_scopes = test_design_scopes
        self.code_indexes = code_indexes
        self.investigations = investigations
        self.build_completions = build_completions
        self.gap_ownership = gap_ownership

    def describe(self, invocation_id: str, project_id: str) -> dict | None:
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in {LIST_EVIDENCE_TOOL, READ_EVIDENCE_TOOL}:
            for observer in (self.images, self.plans, self.acceptance, self.contexts, self.publications, self.indexes, self.test_design_scopes, self.code_indexes, self.investigations, self.build_completions, self.gap_ownership):
                if observer is not None:
                    result = observer.describe(invocation_id, project_id)
                    if result is not None:
                        return result
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.input_payload.get("project_id") != project_id:
            raise PlatformApplicationError("evidence_project_mismatch", "Evidence belongs to another project.", 403)
        receipt = invocation.result.evidence_query if invocation.result else None
        if invocation.status != "completed" or receipt is None:
            return None
        if receipt.project_id != project_id:
            raise PlatformApplicationError("evidence_receipt_mismatch", "Evidence receipt does not match the project.", 409)
        self.evidence.authorize_receipt(receipt)
        return receipt.model_dump(mode="json")

    def expand(self, invocation_id: str) -> EvidencePage:
        invocation = self.invocations.get_tool_invocation(invocation_id)
        self.access.require_invocation_project_scope(invocation)
        receipt = invocation.result.evidence_query if invocation.result else None
        if (invocation.tool_id != READ_EVIDENCE_TOOL or invocation.status != "completed"
                or not isinstance(receipt, EvidenceReadReceipt)):
            raise PlatformApplicationError("evidence_read_required", "A completed evidence read is required.", 409)
        if (receipt.project_id != invocation.input_payload.get("project_id")
                or receipt.evidence.evidence_id != invocation.input_payload.get("evidence_id")
                or receipt.evidence.source_revision_id != invocation.input_payload.get("source_revision_id")):
            raise PlatformApplicationError("evidence_receipt_mismatch", "Evidence receipt does not match the invocation.", 409)
        page = self.evidence.expand(receipt)
        self.access.require_invocation_project_scope(invocation)
        return page
