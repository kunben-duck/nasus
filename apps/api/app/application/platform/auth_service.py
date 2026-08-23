from __future__ import annotations

from dataclasses import dataclass

from .account_models import UserProfile


class AuthServiceError(ValueError):
    """Stable application error raised by identity adapters."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthSessionResult:
    access_token: str
    token_type: str
    expires_at: str
    user: UserProfile


@dataclass(frozen=True)
class AvatarImageContent:
    body: bytes
    mime_type: str


__all__ = ["AuthServiceError", "AuthSessionResult", "AvatarImageContent"]
