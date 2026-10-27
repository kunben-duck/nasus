from contextlib import contextmanager

from fastapi import APIRouter, Path, Query, Response

from ....application.system_image.context_change_impact import ContextChangeImpact
from ....application.system_image.source_context_roots import SourceContextRootsPage
from ....application.system_image.image_query_models import ImageContextImpactInput, SourceContextRootsInput
from ....domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationImpactTooLarge
from ....domain.system_image.context_pack import ContextPackIntegrityError
from ....domain.quality_loop.test_design_scope import TestDesignScopeIntegrityError
from ....application.quality_loop.test_design_results import TestDesignResultIntegrityError
from ....domain.quality_loop.acceptance_specification import AcceptanceIntegrityError
from ....domain.quality_loop.test_design_mapping import TestDesignMappingIntegrityError
from ..dependencies import ContextChangeImpactApp, SourceContextRootApp
from ..dependencies import ContextInvalidationApp
from ..errors import error_response
from .image_revisions import revision_errors
from ..evidence_errors import evidence_read_errors


router = APIRouter()


@contextmanager
def context_impact_errors():
    try:
        yield
    except (DerivationImpactIntegrityError, ContextPackIntegrityError, TestDesignScopeIntegrityError, AcceptanceIntegrityError,
            TestDesignResultIntegrityError, TestDesignMappingIntegrityError) as exc:
        raise error_response("context_impact_integrity_failed", "Context dependencies failed integrity verification.", 502) from exc
    except DerivationImpactTooLarge as exc:
        raise error_response("context_impact_too_large", "Complete context dependencies exceed the query budget; nothing was truncated.", 413) from exc


@router.get("/v1/projects/{project_id}/system-image/context-packs/{context_id}/change-impact", response_model=ContextChangeImpact)
def read_context_change_impact(application: ContextChangeImpactApp, response: Response,
                              project_id: str = Path(..., min_length=1, max_length=128),
                              context_id: str = Path(..., min_length=1, max_length=128),
                              context_artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                              before_revision_id: str = Query(..., min_length=1, max_length=128),
                              after_revision_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    request = ImageContextImpactInput(project_id=project_id, context_id=context_id,
        context_artifact_hash=context_artifact_hash, before_revision_id=before_revision_id, after_revision_id=after_revision_id)
    with revision_errors(), evidence_read_errors(), context_impact_errors():
        return application.read(**request.model_dump())


@router.get("/v1/projects/{project_id}/system-image/context-invalidations/{invalidation_id}")
def read_context_invalidation(application: ContextInvalidationApp, response: Response,
                              project_id: str = Path(..., min_length=1, max_length=128),
                              invalidation_id: str = Path(..., min_length=1, max_length=128)):
    from .context_packs import context_errors
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), context_errors(), context_impact_errors():
        return application.read(project_id, invalidation_id)


@router.get("/v1/projects/{project_id}/system-image/source-context-roots", response_model=SourceContextRootsPage)
def read_source_context_roots(application: SourceContextRootApp, response: Response,
                             project_id: str = Path(..., min_length=1, max_length=128),
                             before_revision_id: str = Query(..., min_length=1, max_length=128),
                             after_revision_id: str = Query(..., min_length=1, max_length=128),
                             after_id: str = Query("", max_length=128), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    request = SourceContextRootsInput(project_id=project_id, before_revision_id=before_revision_id,
        after_revision_id=after_revision_id, after_id=after_id, limit=limit)
    with revision_errors(), evidence_read_errors(), context_impact_errors():
        return application.read(**request.model_dump())
