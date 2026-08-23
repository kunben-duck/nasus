from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Protocol


@dataclass(frozen=True)
class RateLimitCommand:
    scope: str
    principal: str
    limit: int
    window_seconds: int
    occurred_at_epoch: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    scope: str
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_at_epoch: int


class RequestRateLimitPort(Protocol):
    def consume(self, command: RateLimitCommand) -> RateLimitDecision: ...


class RequestRateLimitApplicationService:
    """Applies one shared request budget without knowing its storage backend."""

    def __init__(self, limiter: RequestRateLimitPort) -> None:
        self._limiter = limiter

    def consume(
        self,
        *,
        scope: str,
        principal: str,
        limit: int,
        window_seconds: int,
        occurred_at_epoch: int | None = None,
    ) -> RateLimitDecision:
        normalized_scope = scope.strip().lower()
        normalized_principal = principal.strip()
        if not normalized_scope:
            raise ValueError("rate limit scope is required")
        if not normalized_principal:
            raise ValueError("rate limit principal is required")
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("rate limit and window must be positive")
        return self._limiter.consume(
            RateLimitCommand(
                scope=normalized_scope,
                principal=normalized_principal,
                limit=limit,
                window_seconds=window_seconds,
                occurred_at_epoch=int(time()) if occurred_at_epoch is None else occurred_at_epoch,
            )
        )


__all__ = [
    "RateLimitCommand",
    "RateLimitDecision",
    "RequestRateLimitApplicationService",
    "RequestRateLimitPort",
]
