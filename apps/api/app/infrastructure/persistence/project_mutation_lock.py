from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock, RLock

from sqlalchemy import text

from .database import SessionLocal, engine


class SQLAlchemyProjectMutationLock:
    """Serialize project aggregate mutations across production API instances."""

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._registry_guard = Lock()
        self._fallback_locks: dict[str, RLock] = {}

    @contextmanager
    def acquire(self, project_id: str) -> Iterator[None]:
        lock_key = f"nasus:{self._namespace}:{project_id}"
        if engine.dialect.name == "postgresql":
            session = SessionLocal()
            try:
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": lock_key},
                )
                yield
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
            return

        with self._registry_guard:
            fallback = self._fallback_locks.setdefault(lock_key, RLock())
        with fallback:
            yield


__all__ = ["SQLAlchemyProjectMutationLock"]
