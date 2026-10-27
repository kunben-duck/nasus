from contextlib import contextmanager

from fastapi import APIRouter, Query, Response

from ....domain.system_image.evidence import EvidenceIntegrityError, EvidencePageTooLarge
from ....application.platform.errors import PlatformApplicationError
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ..dependencies import SourceDocumentApp
from ..errors import error_response


router = APIRouter()


@contextmanager
def document_errors():
    try:
        yield
    except KeyError as exc:
        raise error_response("not_found", "Source document is not available.", 404) from exc
    except StaleSourceAccessScope as exc:
        raise error_response("source_access_changed", "Source access changed; reload the document.", 409) from exc
    except SourceAccessDenied as exc:
        raise error_response("source_access_denied", "Source is not available.", 403) from exc
    except EvidenceIntegrityError as exc:
        raise error_response("document_integrity_failed", "Document artifact could not be verified.", 502) from exc
    except EvidencePageTooLarge as exc:
        raise error_response("document_page_too_large", "Request fewer fields.", 413) from exc
    except PlatformApplicationError:
        raise
    except ValueError as exc:
        raise error_response("validation_error", "Invalid source document page.", 400) from exc


@router.get("/v1/projects/{project_id}/system-image/source-documents")
def list_documents(project_id: str, application: SourceDocumentApp, response: Response,
                   source_revision_id: str = Query(..., min_length=1, max_length=64),
                   after_id: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with document_errors():
        return application.list(project_id, source_revision_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/source-documents/{document_revision_id}")
def read_document(project_id: str, document_revision_id: str, application: SourceDocumentApp, response: Response,
                  offset: int = Query(0, ge=0, le=90), limit: int = Query(20, ge=1, le=90)):
    response.headers["Cache-Control"] = "private, no-store"
    with document_errors():
        return application.read(project_id, document_revision_id, offset=offset, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/source-document-extractions")
def list_extractions(project_id: str, application: SourceDocumentApp, response: Response,
                     source_revision_id: str = Query(..., min_length=1, max_length=64),
                     after_id: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with document_errors():
        return application.list_extractions(project_id, source_revision_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/source-document-extractions/{extraction_id}")
def read_extraction(project_id: str, extraction_id: str, application: SourceDocumentApp, response: Response,
                    offset: int = Query(0, ge=0, le=5000), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with document_errors():
        return application.read_extraction(project_id, extraction_id, offset=offset, limit=limit)
