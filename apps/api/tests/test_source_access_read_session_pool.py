from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from apps.api.app.domain.system_image.image_revision import ImageArtifactUnavailable
from apps.api.app.infrastructure.persistence import source_access_read_session as module
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_live_permission_capacity_cannot_starve_business_reads(monkeypatch):
    assert engine.url.get_backend_name() == "postgresql" and engine.url.database.startswith("nasus_test_")
    dedicated = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.05,
                              isolation_level="READ COMMITTED", future=True)
    monkeypatch.setattr(module, "_session_factory", lambda: sessionmaker(bind=dedicated, future=True))
    def competing_read():
        assert module.current_source_access_read_session() is None
        with pytest.raises(ImageArtifactUnavailable, match="capacity"):
            with module.live_source_access_read_session():
                pytest.fail("Full live read pool must fail closed")
        assert module.current_source_access_read_session() is None
        with session_scope() as business:
            assert business.scalar(text("SHOW transaction_read_only")) == "off"
            return business.scalar(text("SELECT 1"))
    try:
        with module.live_source_access_read_session():
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(competing_read).result(timeout=5) == 1
        assert dedicated.pool.checkedout() == 0
        with module.live_source_access_read_session() as session:
            assert session.scalar(text("SELECT 1")) == 1
    finally:
        dedicated.dispose()


def test_delayed_context_opens_a_new_read_only_transaction(monkeypatch):
    dedicated = create_engine(engine.url, pool_size=1, max_overflow=0,
                              isolation_level="READ COMMITTED", future=True)
    monkeypatch.setattr(module, "_session_factory", lambda: sessionmaker(bind=dedicated, future=True))
    try:
        with module.live_source_access_read_session() as first:
            delayed = copy_context()
            assert first.scalar(text("SHOW transaction_read_only")) == "on"
        assert dedicated.pool.checkedout() == 0

        def read_later():
            assert module.current_source_access_read_session() is None
            with module.live_source_access_read_session() as reopened:
                assert reopened is not first
                assert reopened.scalar(text("SHOW transaction_read_only")) == "on"
                assert reopened.scalar(text("SHOW transaction_isolation")) == "read committed"
            assert module.current_source_access_read_session() is None

        delayed.run(read_later)
        assert dedicated.pool.checkedout() == 0
    finally:
        dedicated.dispose()


def test_copied_context_in_another_thread_owns_an_independent_connection(monkeypatch):
    dedicated = create_engine(engine.url, pool_size=2, max_overflow=0,
                              isolation_level="READ COMMITTED", future=True)
    monkeypatch.setattr(module, "_session_factory", lambda: sessionmaker(bind=dedicated, future=True))
    try:
        with module.live_source_access_read_session() as parent:
            copied = copy_context()

            def sibling():
                assert module.current_source_access_read_session() is None
                with module.live_source_access_read_session() as own:
                    assert own is not parent
                    assert own.scalar(text("SHOW transaction_read_only")) == "on"
                assert module.current_source_access_read_session() is None

            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(copied.run, sibling).result(timeout=5)
            assert module.current_source_access_read_session() is parent
            assert parent.scalar(text("SHOW transaction_read_only")) == "on"
        assert dedicated.pool.checkedout() == 0
    finally:
        dedicated.dispose()
