from contextlib import contextmanager

from fastapi import APIRouter, Query, Response
from pydantic import ValidationError

from ....application.quality_loop.automation_inputs import AutomationInputSelection
from ....domain.quality_loop.automation_input import AutomationInputChanged, AutomationInputInvalid
from ..dependencies import AutomationInputApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .acceptance_specifications import acceptance_errors
from .context_packs import context_errors
from .test_design_scopes import scope_errors
from .test_design_mappings import mapping_errors


router = APIRouter()


@contextmanager
def automation_input_errors():
    try:
        yield
    except AutomationInputChanged as exc:
        raise error_response("automation_input_changed", "Automation input changed; inspect again.", 409) from exc
    except AutomationInputInvalid as exc:
        raise error_response("automation_input_incomplete", "Reviewed cases cannot satisfy the complete automation input.", 409) from exc


@router.get("/v1/projects/{project_id}/quality/test-design-mapping-reviews/{revision_id}/automation-input-preview")
def preview_automation_input(project_id: str, revision_id: str, application: AutomationInputApp, response: Response,
        artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"), case_ids: list[str] = Query(...)):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        selection = AutomationInputSelection(project_id=project_id, mapping_revision_id=revision_id,
            mapping_artifact_hash=artifact_hash, case_ids=tuple(case_ids))
    except ValidationError as exc:
        raise error_response("automation_input_selection_invalid", "Select distinct explicit case identities.", 422) from exc
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors():
        return application.prepare(selection)
