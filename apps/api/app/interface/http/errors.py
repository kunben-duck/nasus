from __future__ import annotations

from fastapi import HTTPException

from .request_context import current_request_id, error_envelope


def error_response(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_envelope(
            request_id=current_request_id(),
            code=code,
            message=message,
        ),
    )


def object_ref_id(object_refs: list[str], prefix: str) -> str | None:
    marker = f"{prefix}:"
    for object_ref in object_refs:
        if object_ref.startswith(marker):
            return object_ref.split(":", 1)[1]
    return None
