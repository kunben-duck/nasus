from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Response

from ....application.system_image.evidence_queries import EvidencePage, EvidenceSummary
from ....domain.system_image.evidence import EvidenceIntegrityError, EvidencePageTooLarge
from ..dependencies import EvidenceApp, ToolEvidenceApp
from ..evidence_errors import evidence_read_errors
from ..errors import error_response

router = APIRouter()


@router.get("/v1/projects/{project_id}/system-image/evidence", response_model=list[EvidenceSummary])
def list_source_evidence(
    project_id: str, evidence: EvidenceApp, response: Response,
    source_revision_id: str = Query(..., min_length=1, max_length=128),
    object_id: str = Query(..., min_length=1, max_length=256),
    entity_revision_id: Optional[str] = Query(None, min_length=1, max_length=128),
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return evidence.list_for_alias(project_id, source_revision_id, object_id, entity_revision_id=entity_revision_id)
    except KeyError as exc:
        raise error_response("not_found", "Source evidence was not found.", 404) from exc
    except EvidencePageTooLarge as exc:
        raise error_response("evidence_too_large", "Too many evidence variants for this revision.", 413) from exc
    except EvidenceIntegrityError as exc:
        raise error_response("evidence_integrity_failed", "Archived evidence failed integrity verification.", 502) from exc


@router.get("/v1/projects/{project_id}/system-image/evidence/{evidence_id}", response_model=EvidencePage)
def read_source_evidence(
    project_id: str, evidence_id: str, evidence: EvidenceApp, response: Response,
    start_line: Optional[int] = Query(None, ge=1), max_lines: int = Query(100, ge=1, le=200),
):
    response.headers["Cache-Control"] = "private, no-store"
    with evidence_read_errors():
        return evidence.read(project_id, evidence_id, start_line=start_line, max_lines=max_lines)


@router.get("/v1/tool-invocations/{invocation_id}/evidence", response_model=EvidencePage)
def expand_tool_evidence(invocation_id: str, evidence: ToolEvidenceApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with evidence_read_errors():
        return evidence.expand(invocation_id)
