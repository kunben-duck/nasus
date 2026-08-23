from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from ...application.platform.account_models import UserProfile
from .request_context import error_envelope, resolve_request_id


PUBLIC_PATHS = {"/healthz", "/readyz", "/v1/auth/login", "/v1/auth/register"}
TokenAuthenticator = Callable[[str], Optional[UserProfile]]


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    bearer_token: str
    user_id: str
    user_name: str
    user_email: str
    user_role: str

    @classmethod
    def from_env(cls) -> "AuthConfig":
        return cls(
            mode=os.getenv("NASUS_AUTH_MODE", "dev").strip().lower(),
            bearer_token=os.getenv("NASUS_AUTH_BEARER_TOKEN", "").strip(),
            user_id=os.getenv("NASUS_AUTH_USER_ID", "user_001").strip() or "user_001",
            user_name=os.getenv("NASUS_AUTH_USER_NAME", "Uben").strip() or "Uben",
            user_email=os.getenv("NASUS_AUTH_USER_EMAIL", "uben@example.com").strip() or "uben@example.com",
            user_role=os.getenv("NASUS_AUTH_USER_ROLE", "platform_admin").strip() or "platform_admin",
        )

    @property
    def required(self) -> bool:
        return self.mode in {"required", "prod", "production"}

    @property
    def disabled(self) -> bool:
        return self.mode in {"", "dev", "disabled", "off"}

    def user(self) -> UserProfile:
        return UserProfile(
            id=self.user_id,
            name=self.user_name,
            email=self.user_email,
            role=self.user_role,
        )


def is_public_request(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    if request.url.path in PUBLIC_PATHS:
        return True
    return False


def authenticate_request(
    request: Request,
    config: AuthConfig,
    token_authenticator: TokenAuthenticator | None = None,
) -> UserProfile | JSONResponse:
    header = request.headers.get("authorization", "")
    scheme, _, header_token = header.partition(" ")
    query_token = request.query_params.get("access_token") or ""
    token = header_token if scheme.lower() == "bearer" else query_token

    if token:
        if token_authenticator is not None:
            session_user = token_authenticator(token)
            if session_user is not None:
                return session_user
        if config.bearer_token and token == config.bearer_token:
            return config.user()
        if not is_public_request(request):
            return auth_error(request, "invalid_token", "Bearer token is invalid.", 401)

    if is_public_request(request) or config.disabled:
        return config.user()

    if config.required and not config.bearer_token:
        return auth_error(
            request,
            "auth_not_configured",
            "NASUS_AUTH_MODE requires NASUS_AUTH_BEARER_TOKEN before protected APIs can be served.",
            503,
        )

    if not token:
        return auth_error(request, "missing_token", "Bearer token is required.", 401)
    return auth_error(request, "invalid_token", "Bearer token is invalid.", 401)


def auth_error(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(
            request_id=resolve_request_id(request),
            code=code,
            message=message,
        ),
        headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
    )
