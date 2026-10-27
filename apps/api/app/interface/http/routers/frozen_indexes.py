from fastapi import APIRouter, Query, Response

from ..dependencies import FrozenIndexApp, ContextRetrievalApp
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .image_publications import publication_errors
from ....application.system_image.context_retrieval_inputs import ContextRetrievalSelection
from ....domain.system_image.image_revision import ImageRevisionPageTooLarge
from ..errors import error_response

router = APIRouter()


@router.get("/v1/projects/{project_id}/system-image/context-retrievals/{invocation_id}")
def read_context_retrieval(project_id: str, invocation_id: str, application: ContextRetrievalApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.read(project_id, invocation_id)


@router.get("/v1/projects/{project_id}/system-image/indexes/{generation_id}/context-query-plan")
def context_query_plan(project_id: str, generation_id: str, application: FrozenIndexApp, response: Response,
                       publication_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        try:
            return application.context_retrieval_preview(ContextRetrievalSelection(
                project_id=project_id, publication_id=publication_id, generation_id=generation_id))
        except ImageRevisionPageTooLarge as exc:
            raise error_response("context_retrieval_over_budget",
                "Complete context queries exceed the bounded policy. No AC or field was omitted or sent to a model.", 413) from exc


@router.get("/v1/projects/{project_id}/system-image/indexes")
def index_status(project_id: str, application: FrozenIndexApp, response: Response,
                 publication_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.status(project_id, publication_id)


@router.get("/v1/projects/{project_id}/system-image/indexes/{generation_id}")
def read_index(project_id: str, generation_id: str, application: FrozenIndexApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.describe(project_id, generation_id)


@router.get("/v1/projects/{project_id}/system-image/retrievals/{retrieval_id}")
def read_trace(project_id: str, retrieval_id: str, application: FrozenIndexApp, response: Response,
               offset: int = Query(0, ge=0, le=4096), limit: int = Query(25, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.read_trace(project_id, retrieval_id, offset=offset, limit=limit)
