"""Operation-local connections, never operation-local authorization snapshots."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from threading import get_ident

from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as ConnectionPoolTimeout
from sqlalchemy.orm import sessionmaker

from ...domain.system_image.image_revision import ImageArtifactUnavailable
from .database import engine


_active_session = ContextVar("live_source_access_read_session", default=None)


def _execution_identity():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return get_ident(), task


@dataclass
class _LiveRead:
    session: object
    execution_identity: tuple
    is_open: bool = True


def current_source_access_read_session():
    scope = _active_session.get()
    if scope is not None and scope.is_open and scope.execution_identity == _execution_identity():
        return scope.session
    return None


@lru_cache(maxsize=1)
def _session_factory():
    if engine.dialect.name != "postgresql":
        raise ImageArtifactUnavailable("Live source access sessions require PostgreSQL.")
    # Immutable image snapshots use REPEATABLE READ. Authorization must observe
    # every intervening commit, without holding a business pool connection.
    access_engine = create_engine(engine.url, future=True, pool_pre_ping=True,
        pool_size=4, max_overflow=0, pool_timeout=5, isolation_level="READ COMMITTED")
    return sessionmaker(bind=access_engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def live_source_access_read_session():
    previous = current_source_access_read_session()
    if previous is not None:
        yield previous
        return
    session = _session_factory()()
    token, scope = None, None
    try:
        try:
            session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            session.execute(text("SET TRANSACTION READ ONLY"))
        except ConnectionPoolTimeout as error:
            raise ImageArtifactUnavailable("Live source access capacity is temporarily unavailable.") from error
        scope = _LiveRead(session, _execution_identity())
        token = _active_session.set(scope)
        yield session
    finally:
        # Context copies can outlive this operation. Session.close() alone does
        # not prevent SQLAlchemy from reopening it with a new transaction.
        if scope is not None:
            scope.is_open = False
        if token is not None:
            _active_session.reset(token)
        try:
            session.rollback()
        finally:
            session.close()
