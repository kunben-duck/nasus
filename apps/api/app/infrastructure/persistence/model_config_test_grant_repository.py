from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import delete

from ...application.platform.model_config_test_grants import (
    ModelConfigTestGrantRepositoryPort,
)
from ...application.platform.model_settings import ModelRoute
from .db_models import ModelConfigTestGrantRecord
from .unit_of_work import session_scope


class SQLAlchemyModelConfigTestGrantRepository(
    ModelConfigTestGrantRepositoryPort
):
    """Stores only token digests and atomically consumes matching grants."""

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
        token_hash = self._token_hash(raw_token)
        with session_scope() as session:
            row = session.get(ModelConfigTestGrantRecord, token_hash)
            if row is None:
                row = ModelConfigTestGrantRecord(token_hash=token_hash)
                session.add(row)
            row.route = route
            row.config_id = config_id
            row.fingerprint = fingerprint
            row.issued_at = issued_at
            row.expires_at = expires_at

    def consume(
        self,
        *,
        raw_token: str,
        route: ModelRoute,
        config_id: str | None,
        fingerprint: str,
        consumed_at: datetime,
    ) -> bool:
        config_predicate = (
            ModelConfigTestGrantRecord.config_id.is_(None)
            if config_id is None
            else ModelConfigTestGrantRecord.config_id == config_id
        )
        statement = delete(ModelConfigTestGrantRecord).where(
            ModelConfigTestGrantRecord.token_hash == self._token_hash(raw_token),
            ModelConfigTestGrantRecord.route == route,
            config_predicate,
            ModelConfigTestGrantRecord.fingerprint == fingerprint,
            ModelConfigTestGrantRecord.expires_at > consumed_at,
        )
        with session_scope() as session:
            result = session.execute(statement)
            return result.rowcount == 1

    def purge_expired(self, *, now: datetime) -> int:
        with session_scope() as session:
            result = session.execute(
                delete(ModelConfigTestGrantRecord).where(
                    ModelConfigTestGrantRecord.expires_at <= now
                )
            )
            return int(result.rowcount or 0)

    @staticmethod
    def _token_hash(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


__all__ = ["SQLAlchemyModelConfigTestGrantRepository"]
