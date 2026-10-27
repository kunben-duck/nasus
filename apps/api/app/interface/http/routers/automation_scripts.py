from fastapi import APIRouter, Query, Response
from contextlib import contextmanager

from ....application.quality_loop.automation_script_inputs import ScriptExecutionSelection, ScriptHistoryQuery
from ....application.quality_loop.automation_script_review_inputs import ScriptReviewQuery
from ....domain.quality_loop.automation_script_review import ScriptReviewChanged, ScriptReviewIntegrityError
from ....application.quality_loop.generation_budget import GenerationBudgetInvalid
from ....application.quality_loop.test_design_results import TestDesignResultIntegrityError
from ..dependencies import AutomationScriptApp, AutomationScriptReviewApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .acceptance_specifications import acceptance_errors
from .context_packs import context_errors
from .image_revisions import revision_errors
from .test_design_scopes import scope_errors
from .test_design_mappings import mapping_errors
from .automation_inputs import automation_input_errors
from .case_approvals import case_approval_errors


router = APIRouter()


@contextmanager
def script_review_errors():
    try:
        yield
    except ScriptReviewChanged as exc:
        raise error_response("automation_review_changed", "Script inputs or review head changed; inspect again.", 409) from exc
    except ScriptReviewIntegrityError as exc:
        raise error_response("automation_review_invalid", "Script review provenance cannot be verified.", 502) from exc
    except TestDesignResultIntegrityError as exc:
        raise error_response("automation_archive_invalid", "Automation draft provenance cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/automation-script-history")
def list_script_history(project_id: str, application: AutomationScriptApp, response: Response,
                        mapping_revision_id: str = Query(..., min_length=1, max_length=128),
                        mapping_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                        after_id: str = Query("", max_length=128), limit: int = Query(10, ge=1, le=20)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors(), script_review_errors():
        return application.history(ScriptHistoryQuery(project_id=project_id, mapping_revision_id=mapping_revision_id,
            mapping_artifact_hash=mapping_artifact_hash, after_id=after_id, limit=limit))


@router.get("/v1/projects/{project_id}/quality/automation-script-revisions/{revision_id}/review")
def inspect_script_review(project_id: str, revision_id: str, application: AutomationScriptReviewApp, response: Response,
                          artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors(), script_review_errors():
        return application.inspect(ScriptReviewQuery(project_id=project_id, script_revision_id=revision_id, script_artifact_hash=artifact_hash))


@router.get("/v1/projects/{project_id}/quality/automation-script-reviews/{revision_id}")
def read_script_review(project_id: str, revision_id: str, application: AutomationScriptReviewApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors(), script_review_errors():
        return application.read(project_id, revision_id)


@router.post("/v1/projects/{project_id}/quality/automation-script-previews")
def preview_script_generation(project_id: str, selection: ScriptExecutionSelection, application: AutomationScriptApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    if selection.project_id != project_id:
        raise error_response("automation_scope_mismatch", "Automation preview project differs from its route.", 422)
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors():
        try:
            return application.preview(selection)
        except GenerationBudgetInvalid as exc:
            raise error_response("automation_budget_invalid", "Complete automation input exceeds its operator budget or policy.", 409) from exc


@router.get("/v1/projects/{project_id}/quality/automation-script-revisions/{revision_id}")
def read_script_revision(project_id: str, revision_id: str, application: AutomationScriptApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), case_approval_errors():
        try:
            return application.read(project_id, revision_id)
        except TestDesignResultIntegrityError as exc:
            raise error_response("automation_archive_invalid", "Automation draft provenance cannot be verified.", 502) from exc
