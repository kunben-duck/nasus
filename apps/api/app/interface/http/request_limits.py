from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ...application.platform.account_models import UserProfile


EXEMPT_PATHS = {"/healthz", "/readyz"}
AUTH_PATHS = {"/v1/auth/login", "/v1/auth/register"}
AGENT_WRITE_PREFIXES = (
    "/v1/agent-goals",
    "/v1/conversations",
    "/v1/tool-invocations",
)


@dataclass(frozen=True)
class RequestLimitTarget:
    scope: str
    principal: str


def request_limit_target(
    request: Request,
    user: UserProfile | None,
) -> RequestLimitTarget | None:
    path = request.url.path
    if request.method == "OPTIONS" or path in EXEMPT_PATHS:
        return None
    if path in AUTH_PATHS:
        return RequestLimitTarget(scope="auth", principal=f"ip:{_client_host(request)}")
    if not path.startswith("/v1/") and path != "/metrics":
        return None
    principal = f"user:{user.id}" if user is not None else f"ip:{_client_host(request)}"
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith(
        AGENT_WRITE_PREFIXES
    ):
        return RequestLimitTarget(scope="agent", principal=principal)
    return RequestLimitTarget(scope="api", principal=principal)


def _client_host(request: Request) -> str:
    # Do not trust X-Forwarded-For without an explicit trusted-proxy boundary.
    return request.client.host if request.client is not None else "unknown"


__all__ = ["RequestLimitTarget", "request_limit_target"]
