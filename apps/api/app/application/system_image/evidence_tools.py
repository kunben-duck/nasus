from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from ...domain.system_image.evidence import EvidenceIntegrityError
from .evidence_queries import EvidencePage, EvidenceQueryApplicationService
from .evidence_tool_models import (
    EvidenceListInput, EvidenceListReceipt, EvidenceReadInput, EvidenceReadReceipt,
    EvidenceToolReceipt,
)


class EvidenceToolPort(Protocol):
    def list(self, request: EvidenceListInput) -> EvidenceListReceipt: ...

    def read(self, request: EvidenceReadInput) -> EvidenceReadReceipt: ...

    def expand(self, receipt: EvidenceReadReceipt) -> EvidencePage: ...

    def authorize_receipt(self, receipt: EvidenceToolReceipt) -> None: ...


class EvidenceToolApplicationService:
    def __init__(self, queries: EvidenceQueryApplicationService) -> None:
        self.queries = queries

    def list(self, request: EvidenceListInput) -> EvidenceListReceipt:
        items = self.queries.list_for_alias(
            request.project_id, request.source_revision_id, request.object_id,
            entity_revision_id=request.entity_revision_id,
        )
        return EvidenceListReceipt(**request.model_dump(), items=items)

    def read(self, request: EvidenceReadInput) -> EvidenceReadReceipt:
        page = self.queries.read(
            request.project_id, request.evidence_id, start_line=request.start_line,
            max_lines=request.max_lines, source_revision_id=request.source_revision_id,
        )
        return self._receipt(request.project_id, page)

    def expand(self, receipt: EvidenceReadReceipt) -> EvidencePage:
        # Re-read through the same authorization/integrity boundary, not a result cache.
        page = self.queries.read(
            receipt.project_id, receipt.evidence.evidence_id,
            source_revision_id=receipt.evidence.source_revision_id,
            start_line=receipt.start_line, max_lines=receipt.end_line - receipt.start_line + 1,
        )
        if self._receipt(receipt.project_id, page) != receipt:
            raise EvidenceIntegrityError("evidence read receipt mismatch")
        return page

    def authorize_receipt(self, receipt: EvidenceToolReceipt) -> None:
        if isinstance(receipt, EvidenceListReceipt):
            self.queries.require_revision_access(receipt.project_id, receipt.source_revision_id)
        items = receipt.items if isinstance(receipt, EvidenceListReceipt) else [receipt.evidence]
        for binding_id in {item.binding_id for item in items}:
            self.queries.require_binding_access(receipt.project_id, binding_id)

    @staticmethod
    def _receipt(project_id: str, page: EvidencePage) -> EvidenceReadReceipt:
        metadata = asdict(page)
        del metadata["content"]
        return EvidenceReadReceipt(project_id=project_id, **metadata)
