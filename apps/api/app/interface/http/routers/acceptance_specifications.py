from contextlib import contextmanager

from fastapi import APIRouter, Query, Response

from ....domain.quality_loop.acceptance_specification import AcceptanceIntegrityError, StaleAcceptanceSpecification
from ..dependencies import AcceptanceApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors


router = APIRouter()


@contextmanager
def acceptance_errors():
    try:
        yield
    except AcceptanceIntegrityError as exc:
        raise error_response("acceptance_integrity_failed", "Acceptance source or authority could not be verified.", 502) from exc
    except StaleAcceptanceSpecification as exc:
        raise error_response("acceptance_authority_changed", "Acceptance authority changed; inspect again.", 409) from exc


@router.get("/v1/projects/{project_id}/quality/acceptance-specifications")
def inspect_acceptance(project_id: str, application: AcceptanceApp, response: Response,
                       image_revision_id: str = Query(..., min_length=1, max_length=128),
                       image_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                       object_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors():
        return application.inspect(project_id, image_revision_id, image_artifact_hash, object_id)


@router.get("/v1/projects/{project_id}/quality/acceptance-specifications/{revision_id}")
def read_acceptance(project_id: str, revision_id: str, application: AcceptanceApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors():
        return application.read(project_id, revision_id)
