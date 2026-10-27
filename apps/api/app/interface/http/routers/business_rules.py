from fastapi import APIRouter, Query, Response

from ..dependencies import BusinessRuleApp
from ..evidence_errors import evidence_read_errors
from .acceptance_specifications import acceptance_errors
from .image_revisions import revision_errors


router = APIRouter()


@router.get("/v1/projects/{project_id}/quality/business-rules")
def inspect_business_rule(project_id: str, application: BusinessRuleApp, response: Response,
                          image_revision_id: str = Query(..., min_length=1, max_length=128),
                          image_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                          object_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors():
        return application.inspect(project_id, image_revision_id, image_artifact_hash, object_id)


@router.get("/v1/projects/{project_id}/quality/business-rules/{revision_id}")
def read_business_rule(project_id: str, revision_id: str, application: BusinessRuleApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors():
        return application.read(project_id, revision_id)
