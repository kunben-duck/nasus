from contextlib import contextmanager

from fastapi import APIRouter, Query, Response

from ....application.platform.errors import PlatformApplicationError
from ....application.system_image.code_index_lifecycle import CodeIndexListInput, CodeIndexStatusInput, CodeIndexListPage, CodeIndexStatusReceipt
from ....domain.system_image.code_index_generation import CodeIndexLeaseLost
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ..dependencies import CodeIndexLifecycleApp
from ..errors import error_response


router = APIRouter()


@contextmanager
def index_errors():
    try:
        yield
    except KeyError as error:
        raise error_response("not_found", "Code index generation was not found.", 404) from error
    except StaleSourceAccessScope as error:
        raise error_response("source_access_changed", "Source access changed; reload the index.", 409) from error
    except SourceAccessDenied as error:
        raise error_response("source_access_denied", "Code index source is not available.", 403) from error
    except CodeIndexLeaseLost as error:
        raise error_response("code_index_integrity_failed", "Code index lifecycle metadata failed verification.", 502) from error
    except PlatformApplicationError:
        raise
    except ValueError as error:
        raise error_response("validation_error", "Invalid code index query.", 400) from error


@router.get("/v1/projects/{project_id}/system-image/code-indexes", response_model=CodeIndexListPage)
def list_code_indexes(project_id: str, application: CodeIndexLifecycleApp, response: Response,
                      binding_id: str = Query(..., min_length=1, max_length=128),
                      after_id: str = Query("", max_length=128), limit: int = Query(10, ge=1, le=30)):
    response.headers["Cache-Control"] = "private, no-store"
    with index_errors():
        return application.list(CodeIndexListInput(project_id=project_id, binding_id=binding_id, after_id=after_id, limit=limit))


@router.get("/v1/projects/{project_id}/system-image/code-indexes/{generation_id}", response_model=CodeIndexStatusReceipt)
def read_code_index(project_id: str, generation_id: str, application: CodeIndexLifecycleApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with index_errors():
        return application.read(CodeIndexStatusInput(project_id=project_id, generation_id=generation_id))
