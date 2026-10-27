from contextlib import contextmanager
import json
from typing import Literal, Optional

from fastapi import APIRouter, Query, Response
from pydantic import ValidationError

from ....application.system_image.context_pack_inputs import ContextPreviewInput, ContextListInput
from ....domain.system_image.context_pack import ContextPackIntegrityError, ContextPackChanged, MandatoryContextTooLarge
from ....domain.system_image.context_authorities import ContextAuthorityRegistrationRequired
from ..dependencies import ContextPackApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .acceptance_specifications import acceptance_errors

router = APIRouter()


def unique_bindings(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate retrieval binding")
    return value


@contextmanager
def context_errors():
    try:
        yield
    except ContextPackIntegrityError as exc:
        raise error_response("context_integrity_failed", "Context could not be verified.", 502) from exc
    except ContextAuthorityRegistrationRequired as exc:
        raise error_response("context_authority_registration_required", "Register the original historical context dependencies with independent confirmation before use.", 409) from exc
    except ContextPackChanged as exc:
        raise error_response("context_inputs_changed", "Context inputs changed; preview again.", 409) from exc
    except MandatoryContextTooLarge as exc:
        raise error_response("mandatory_context_over_budget", "Mandatory context exceeds budget; split scope or increase it. No requirement was discarded.", 422) from exc


@router.get("/v1/projects/{project_id}/system-image/context-authority-backfill")
def pending_context_authorities(project_id: str, application: ContextPackApp, response: Response,
                               after_id: str = Query("", max_length=128), limit: int = Query(3, ge=1, le=5)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors():
        return application.pending_authority_registrations(project_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/context-packs/preview")
def preview_context(project_id: str, application: ContextPackApp, response: Response,
                    image_revision_id: str = Query(..., min_length=1, max_length=128),
                    image_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                    purpose: Literal["test_design"] = Query("test_design"),
                    policy_revision: Literal["nasus.test-design-context.v1", "nasus.test-design-context.v2", "nasus.test-design-context.v3", "nasus.test-design-context.v4", "nasus.test-design-context.v5"] = Query("nasus.test-design-context.v1"),
                    publication_id: Optional[str] = Query(None, min_length=1, max_length=128),
                    retrieval_bindings: Optional[str] = Query(None, max_length=65536),
                    max_tokens: int = Query(12000, ge=512, le=32768), candidate_limit: int = Query(5, ge=1, le=10)):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        request = ContextPreviewInput(project_id=project_id, image_revision_id=image_revision_id,
            image_artifact_hash=image_artifact_hash, purpose=purpose, policy_revision=policy_revision,
            publication_id=publication_id, max_tokens=max_tokens, candidate_limit=candidate_limit,
            retrieval_bindings=json.loads(retrieval_bindings, object_pairs_hook=unique_bindings) if retrieval_bindings is not None else None)
    except (ValidationError, ValueError) as exc:
        raise error_response("invalid_context_request", "Context policy, publication and retrieval selections do not match.", 422) from exc
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors():
        return application.preview(request)


@router.get("/v1/projects/{project_id}/system-image/context-packs/{context_id}")
def read_context(project_id: str, context_id: str, application: ContextPackApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors():
        return application.read(project_id, context_id)


@router.get("/v1/projects/{project_id}/system-image/context-packs")
def list_contexts(project_id: str, application: ContextPackApp, response: Response,
                  image_revision_id: str = Query(..., min_length=1, max_length=128),
                  image_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                  after_id: str = Query("", max_length=128), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors():
        return application.list(ContextListInput(project_id=project_id, image_revision_id=image_revision_id,
            image_artifact_hash=image_artifact_hash, after_id=after_id, limit=limit))
