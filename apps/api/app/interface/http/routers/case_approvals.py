from contextlib import contextmanager

from fastapi import APIRouter, Query, Response
from pydantic import ValidationError

from ....application.quality_loop.automation_inputs import AutomationInputSelection
from ....domain.quality_loop.case_approval import CaseApprovalChanged, CaseApprovalIntegrityError
from ..dependencies import CaseApprovalApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .acceptance_specifications import acceptance_errors
from .context_packs import context_errors
from .test_design_scopes import scope_errors
from .test_design_mappings import mapping_errors
from .automation_inputs import automation_input_errors


router = APIRouter()


@contextmanager
def case_approval_errors():
    try:
        yield
    except CaseApprovalChanged as error:
        raise error_response("case_admission_changed", "Case admission changed; inspect again.", 409) from error
    except CaseApprovalIntegrityError as error:
        raise error_response("case_admission_integrity_failed", "Case admission could not be verified.", 502) from error


@router.get("/v1/projects/{project_id}/quality/test-design-case-approvals/preview")
def preview_case_approval(project_id: str, application: CaseApprovalApp, response: Response,
        mapping_revision_id: str = Query(...), mapping_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
        case_ids: list[str] = Query(...)):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        selection = AutomationInputSelection(project_id=project_id, mapping_revision_id=mapping_revision_id,
            mapping_artifact_hash=mapping_artifact_hash, case_ids=tuple(case_ids))
    except ValidationError as error:
        raise error_response("case_admission_selection_invalid", "Select distinct explicit case identities.", 422) from error
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors():
        return application.preview(selection)


@router.get("/v1/projects/{project_id}/quality/test-design-case-approvals/{revision_id}")
def read_case_approval(project_id: str, revision_id: str, application: CaseApprovalApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors():
        return application.read(project_id, revision_id)
