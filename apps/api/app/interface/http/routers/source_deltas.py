from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Query, Response

from ....application.platform.errors import PlatformApplicationError
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ....domain.system_image.source_delta import (
    SourceDeltaIntegrityError, SourceDeltaPageTooLarge, SourceDeltaUnavailable,
)
from ....application.system_image.source_deltas import SourceDeltaPage
from ..dependencies import SourceDeltaApp
from ..errors import error_response


router = APIRouter()


@contextmanager
def source_delta_errors():
    try:
        yield
    except KeyError as exc:
        raise error_response("not_found", "Source revisions are not available.", 404) from exc
    except StaleSourceAccessScope as exc:
        raise error_response("source_access_changed", "Source access changed; reload the comparison.", 409) from exc
    except SourceAccessDenied as exc:
        raise error_response("source_access_denied", "Source is not available.", 403) from exc
    except SourceDeltaIntegrityError as exc:
        raise error_response("source_delta_integrity_failed", "Source delta failed integrity verification.", 502) from exc
    except SourceDeltaUnavailable as exc:
        raise error_response("source_delta_unavailable", "Source delta archive is unavailable.", 503) from exc
    except SourceDeltaPageTooLarge as exc:
        raise error_response("source_delta_page_too_large", "Request fewer changes; this page exceeds 64 KiB.", 413) from exc
    except PlatformApplicationError:
        raise
    except ValueError as exc:
        raise error_response("validation_error", "Invalid source delta comparison or page.", 400) from exc


@router.get("/v1/projects/{project_id}/system-image/source-delta", response_model=SourceDeltaPage)
def read_source_delta(project_id: str, application: SourceDeltaApp, response: Response,
                      before_revision_id: str = Query(..., min_length=1, max_length=128),
                      after_revision_id: str = Query(..., min_length=1, max_length=128),
                      section: Literal["files", "rename_candidates"] = "files",
                      kind: Optional[str] = Query(None, max_length=20),
                      offset: int = Query(0, ge=0, le=100000), limit: int = Query(50, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with source_delta_errors():
        return application.read(project_id, before_revision_id, after_revision_id,
                                section=section, kind=kind, offset=offset, limit=limit)
