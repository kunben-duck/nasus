"""Bounded, independent connections for compilation-local immutable reads."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as ConnectionPoolTimeout
from sqlalchemy.orm import sessionmaker

from ...application.operation_read_scope import OperationReadScope
from ...domain.system_image.image_revision import ImageArtifactUnavailable
from .database import engine


_active_snapshot = ContextVar("immutable_image_read_snapshot", default=None)
CONTEXT_PROVENANCE_CACHE = "nasus.context.provenance.v1"


def current_image_read_snapshot():
    scope = _active_snapshot.get()
    return scope.value if scope is not None and scope.is_current else None


@lru_cache(maxsize=1)
def _session_factory():
    if engine.dialect.name != "postgresql":
        raise ImageArtifactUnavailable("Verified image snapshots require PostgreSQL.")
    # A compilation still uses the main pool for live ACL/authority reads.
    # Holding that pool's connections here could deadlock concurrent compilers.
    snapshot_engine = create_engine(engine.url, future=True, pool_pre_ping=True,
        pool_size=4, max_overflow=0, pool_timeout=5, isolation_level="REPEATABLE READ")
    return sessionmaker(bind=snapshot_engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def image_read_snapshot_scope():
    session = _session_factory()()
    token, scope = None, None
    try:
        try:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
        except ConnectionPoolTimeout as error:
            raise ImageArtifactUnavailable("Verified image read capacity is temporarily unavailable.") from error
        scope = OperationReadScope((session, {}))
        token = _active_snapshot.set(scope)
        yield session
    finally:
        # Copies inherited by tasks/to_thread may outlive this context. Closing
        # SQLAlchemy alone does not prevent that Session from reopening.
        if scope is not None:
            scope.close()
        if token is not None:
            _active_snapshot.reset(token)
        # Never commit facts or retain a snapshot beyond its operation.
        try:
            info = getattr(session, "info", None)
            if info is not None:
                info.pop(CONTEXT_PROVENANCE_CACHE, None)
        finally:
            try:
                session.rollback()
            finally:
                session.close()
