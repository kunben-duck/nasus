from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from ....application.system_image.publications import PublicationTarget, RollbackTarget
from ....domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from ..dependencies import ImagePublicationApp
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors

router = APIRouter()


@contextmanager
def publication_errors():
    try:
        yield
    except PublicationChanged as exc:
        raise HTTPException(409, detail={"error": {"code": "publication_inputs_changed", "message": str(exc)}}) from exc
    except PublicationIntegrityError as exc:
        raise HTTPException(502, detail={"error": {"code": "publication_integrity_failed", "message": "Publication could not be verified."}}) from exc


@router.get("/v1/projects/{project_id}/system-image/publications/preview")
def preview(project_id: str, application: ImagePublicationApp, response: Response,
            image_revision_id: str = Query(..., min_length=1, max_length=128),
            image_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
            target_baseline_id: str = Query(..., min_length=1, max_length=128),
            expected_head_id: Optional[str] = Query(None, min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.preview(PublicationTarget(project_id=project_id, image_revision_id=image_revision_id,
            image_artifact_hash=image_artifact_hash, target_baseline_id=target_baseline_id, expected_head_id=expected_head_id))


@router.get("/v1/projects/{project_id}/system-image/publications")
def history(project_id: str, application: ImagePublicationApp, response: Response,
            baseline_id: str = Query(..., min_length=1, max_length=128),
            after_sequence: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.history(project_id, baseline_id, after_sequence=after_sequence, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/publications/rollback-preview")
def rollback_preview(project_id: str, application: ImagePublicationApp, response: Response,
                     image_revision_id: str = Query(..., min_length=1, max_length=128),
                     image_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                     target_baseline_id: str = Query(..., min_length=1, max_length=128),
                     expected_head_id: str = Query(..., min_length=1, max_length=128),
                     rollback_publication_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), publication_errors():
        return application.preview(RollbackTarget(project_id=project_id, image_revision_id=image_revision_id,
            image_artifact_hash=image_artifact_hash, target_baseline_id=target_baseline_id,
            expected_head_id=expected_head_id, rollback_publication_id=rollback_publication_id))
