from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .model_settings import ModelRoute


class ModelConfigTestGrantRepositoryPort(Protocol):
    """Durable, one-time authorization for saving a tested model profile."""

    def issue(
        self,
        *,
        raw_token: str,
        route: ModelRoute,
        config_id: str | None,
        fingerprint: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        ...

    def consume(
        self,
        *,
        raw_token: str,
        route: ModelRoute,
        config_id: str | None,
        fingerprint: str,
        consumed_at: datetime,
    ) -> bool:
        ...

    def purge_expired(self, *, now: datetime) -> int:
        ...


__all__ = ["ModelConfigTestGrantRepositoryPort"]
