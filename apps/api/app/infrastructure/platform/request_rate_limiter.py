from __future__ import annotations

from hashlib import sha256
from threading import Lock
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ...application.platform.request_rate_limits import (
    RateLimitCommand,
    RateLimitDecision,
    RequestRateLimitPort,
)
from ..persistence.db_models import ApiRateLimitWindowRecord


class SQLAlchemyFixedWindowRateLimiter(RequestRateLimitPort):
    """Atomic shared fixed-window limiter for PostgreSQL and local SQLite tests."""

    def __init__(self, session_factory: Any, *, cleanup_interval: int = 500) -> None:
        self._session_factory = session_factory
        self._cleanup_interval = max(cleanup_interval, 1)
        self._request_count = 0
        self._cleanup_lock = Lock()

    def consume(self, command: RateLimitCommand) -> RateLimitDecision:
        window_start = (
            command.occurred_at_epoch // command.window_seconds
        ) * command.window_seconds
        reset_at = window_start + command.window_seconds
        scope_key = self._scope_key(command.scope, command.principal)
        now = command.occurred_at_epoch

        with self._session_factory() as session:
            bind = session.get_bind()
            dialect_name = bind.dialect.name
            values = {
                "scope_key": scope_key,
                "scope": command.scope,
                "window_started_at_epoch": window_start,
                "request_count": 1,
                "expires_at_epoch": reset_at,
                "updated_at_epoch": now,
            }
            if dialect_name == "postgresql":
                statement = postgresql_insert(ApiRateLimitWindowRecord).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=["scope_key", "window_started_at_epoch"],
                    set_={
                        "request_count": ApiRateLimitWindowRecord.request_count + 1,
                        "expires_at_epoch": reset_at,
                        "updated_at_epoch": now,
                    },
                ).returning(ApiRateLimitWindowRecord.request_count)
                count = int(session.execute(statement).scalar_one())
            elif dialect_name == "sqlite":
                statement = sqlite_insert(ApiRateLimitWindowRecord).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=["scope_key", "window_started_at_epoch"],
                    set_={
                        "request_count": ApiRateLimitWindowRecord.request_count + 1,
                        "expires_at_epoch": reset_at,
                        "updated_at_epoch": now,
                    },
                ).returning(ApiRateLimitWindowRecord.request_count)
                count = int(session.execute(statement).scalar_one())
            else:
                count = self._consume_with_locking(session, values)
            session.commit()

        self._maybe_cleanup(now)
        allowed = count <= command.limit
        return RateLimitDecision(
            allowed=allowed,
            scope=command.scope,
            limit=command.limit,
            remaining=max(command.limit - count, 0),
            retry_after_seconds=max(reset_at - now, 1) if not allowed else 0,
            reset_at_epoch=reset_at,
        )

    @staticmethod
    def _scope_key(scope: str, principal: str) -> str:
        digest = sha256(f"{scope}:{principal}".encode("utf-8")).hexdigest()
        return f"{scope}:{digest}"

    @staticmethod
    def _consume_with_locking(session: Any, values: dict[str, Any]) -> int:
        row = session.execute(
            select(ApiRateLimitWindowRecord)
            .where(
                ApiRateLimitWindowRecord.scope_key == values["scope_key"],
                ApiRateLimitWindowRecord.window_started_at_epoch
                == values["window_started_at_epoch"],
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            session.add(ApiRateLimitWindowRecord(**values))
            return 1
        row.request_count += 1
        row.updated_at_epoch = values["updated_at_epoch"]
        return row.request_count

    def _maybe_cleanup(self, now: int) -> None:
        with self._cleanup_lock:
            self._request_count += 1
            if self._request_count % self._cleanup_interval:
                return
        with self._session_factory() as session:
            session.execute(
                delete(ApiRateLimitWindowRecord).where(
                    ApiRateLimitWindowRecord.expires_at_epoch < now
                )
            )
            session.commit()


__all__ = ["SQLAlchemyFixedWindowRateLimiter"]
