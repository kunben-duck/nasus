from contextlib import contextmanager

from fastapi import APIRouter, Query, Response

from ....domain.quality_loop.test_design_scope import TestDesignScopeChanged, TestDesignScopeIntegrityError
from ....domain.quality_loop.test_design_generation import TestDesignGenerationInvalid
from ....application.quality_loop.test_design_generation import GenerationSelection
from ....application.quality_loop.test_design_results import TestDesignResultIntegrityError
from ....application.quality_loop.generation_job_ports import GenerationHistoryRequest
from ..dependencies import TestDesignScopeApp, TestDesignGenerationApp, TestDesignResultApp, GenerationJobApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .acceptance_specifications import acceptance_errors
from .context_packs import context_errors


router = APIRouter()


@contextmanager
def scope_errors():
    try:
        yield
    except TestDesignScopeChanged as exc:
        raise error_response("test_design_scope_changed", "Scope changed; inspect again.", 409) from exc
    except TestDesignScopeIntegrityError as exc:
        raise error_response("test_design_scope_integrity_failed", "Scope could not be verified.", 502) from exc
    except TestDesignGenerationInvalid as exc:
        raise error_response("test_design_generation_input_invalid", "Complete a current scope with all pinned source oracles before generation preflight.", 409) from exc
    except TestDesignResultIntegrityError as exc:
        raise error_response("test_design_result_integrity_failed", "Generation result could not be verified.", 502) from exc
    except PermissionError as exc:
        raise error_response("test_design_job_access_denied", "Current project administrator access is required.", 403) from exc


@router.get("/v1/projects/{project_id}/quality/test-design-scopes")
def inspect_scope(project_id: str, application: TestDesignScopeApp, response: Response,
                  context_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors():
        return application.inspect(project_id, context_id)


@router.get("/v1/projects/{project_id}/quality/test-design-scopes/{revision_id}")
def read_scope(project_id: str, revision_id: str, application: TestDesignScopeApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors():
        return application.read(project_id, revision_id)


@router.get("/v1/projects/{project_id}/quality/test-design-scopes/{revision_id}/generation-preview")
def preview_generation(project_id: str, revision_id: str, application: TestDesignGenerationApp, response: Response,
                       artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors():
        return application.preview(GenerationSelection(project_id=project_id, scope_revision_id=revision_id, scope_artifact_hash=artifact_hash))


@router.get("/v1/projects/{project_id}/quality/test-design-results/{generation_id}")
def read_generation_result(project_id: str, generation_id: str, application: TestDesignResultApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors():
        return application.read_public(project_id, generation_id)


@router.get("/v1/projects/{project_id}/quality/test-design-jobs")
def list_generation_jobs(project_id: str, application: GenerationJobApp, response: Response,
                         scope_revision_id: str = Query(..., min_length=1, max_length=128),
                         scope_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                         after_id: str = Query("", max_length=128), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors():
        return application.history(GenerationHistoryRequest(project_id=project_id, scope_revision_id=scope_revision_id,
            scope_artifact_hash=scope_artifact_hash, after_id=after_id, limit=limit))
