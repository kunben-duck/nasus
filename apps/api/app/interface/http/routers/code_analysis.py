from contextlib import contextmanager
from typing import Literal
from typing import Optional

from fastapi import APIRouter, Query, Response

from ....application.platform.errors import PlatformApplicationError
from ....application.system_image.code_analysis_queries import (
    CodeAnalysisIntegrityError, CodeAnalysisListPage, CodeAnalysisPage, CodeAnalysisPageTooLarge, CodeSourceRevisionPage,
)
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ..dependencies import CodeAnalysisApp
from ..errors import error_response


router = APIRouter()


@contextmanager
def analysis_errors():
    try:
        yield
    except KeyError as exc:
        raise error_response("not_found", "Code analysis was not found at this source revision.", 404) from exc
    except StaleSourceAccessScope as exc:
        raise error_response("source_access_changed", "Source access changed; reload the report.", 409) from exc
    except SourceAccessDenied as exc:
        raise error_response("source_access_denied", "Source is not available.", 403) from exc
    except CodeAnalysisIntegrityError as exc:
        raise error_response("analysis_integrity_failed", "Code analysis failed integrity verification.", 502) from exc
    except CodeAnalysisPageTooLarge as exc:
        raise error_response("analysis_page_too_large", "Request fewer observations; this page exceeds 64 KiB.", 413) from exc
    except PlatformApplicationError:
        raise
    except ValueError as exc:
        raise error_response("validation_error", "Invalid code analysis page.", 400) from exc


@router.get("/v1/projects/{project_id}/system-image/code-source-revisions", response_model=CodeSourceRevisionPage)
def list_code_source_revisions(project_id: str, application: CodeAnalysisApp, response: Response,
                               after_id: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with analysis_errors():
        return application.list_source_revisions(project_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/source-analyses", response_model=CodeAnalysisListPage)
def list_code_analyses(project_id: str, application: CodeAnalysisApp, response: Response,
                       source_revision_id: str = Query(..., min_length=1, max_length=64),
                       after_id: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with analysis_errors():
        return application.list_for_revision(project_id, source_revision_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/source-analyses/{analysis_id}", response_model=CodeAnalysisPage)
def read_code_analysis(project_id: str, analysis_id: str, application: CodeAnalysisApp, response: Response,
                       source_revision_id: str = Query(..., min_length=1, max_length=64),
                       section: Literal["files", "facts", "entities", "relationships"] = "files",
                       offset: int = Query(0, ge=0, le=100000), limit: int = Query(50, ge=1, le=100),
                       kind: Optional[str] = Query(None, max_length=40), status: Optional[str] = Query(None, max_length=20)):
    response.headers["Cache-Control"] = "private, no-store"
    with analysis_errors():
        return application.read(project_id, source_revision_id, analysis_id, section=section, offset=offset, limit=limit,
                                kind=kind, status=status)
