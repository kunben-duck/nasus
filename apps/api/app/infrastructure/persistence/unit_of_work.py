from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .database import SessionLocal


@contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
