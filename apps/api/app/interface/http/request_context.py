from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import Request


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_request_id: ContextVar[str | None] = ContextVar("nasus_request_id", default=None)


def resolve_request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if existing:
        return str(existing)
    candidate = request.headers.get("x-request-id", "").strip()
    request_id = candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else f"req_{uuid4().hex}"
    request.state.request_id = request_id
    return request_id


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str:
    return _request_id.get() or f"req_{uuid4().hex}"


def error_envelope(
    *,
    code: str,
    message: str,
    request_id: str | None = None,
    details: dict | None = None,
    retry_after: int | None = None,
) -> dict:
    return {
        "request_id": request_id or current_request_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "retry_after": retry_after,
        },
    }


__all__ = [
    "REQUEST_ID_HEADER",
    "bind_request_id",
    "current_request_id",
    "error_envelope",
    "reset_request_id",
    "resolve_request_id",
]
