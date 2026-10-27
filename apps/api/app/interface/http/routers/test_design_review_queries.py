from fastapi import APIRouter, Query, Response

from ....application.quality_loop.test_design_review_queries import ReviewDraftListInput
from ....domain.system_image.source_access import SourceAccessDenied
from ..dependencies import TestDesignResultApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .acceptance_specifications import acceptance_errors
from .context_packs import context_errors
from .test_design_scopes import scope_errors


router = APIRouter()


@router.get("/v1/projects/{project_id}/quality/test-design-review-drafts")
def list_review_drafts(project_id: str, application: TestDesignResultApp, response: Response,
                       after_id: str = Query("", max_length=128), limit: int = Query(3, ge=1, le=5)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors():
        try:
            return application.list_for_review(ReviewDraftListInput(project_id=project_id, after_id=after_id, limit=limit))
        except SourceAccessDenied:
            raise
        except PermissionError as exc:
            raise error_response("test_design_review_access_denied", "Current project reviewer access is required.", 403) from exc
