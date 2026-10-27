import asyncio
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import TimeoutError as ConnectionPoolTimeout

from apps.api.app.domain.system_image.image_revision import ImageArtifactUnavailable
from apps.api.app.infrastructure.persistence import source_access_read_session as module


def test_live_access_sessions_never_create_a_non_postgresql_fallback(monkeypatch):
    monkeypatch.setattr(module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(module, "create_engine", lambda *args, **kwargs: pytest.fail("No fallback engine"))
    with pytest.raises(ImageArtifactUnavailable, match="PostgreSQL"):
        module._session_factory.__wrapped__()


def test_live_access_pool_is_separate_bounded_and_read_committed(monkeypatch):
    url, binding, calls = object(), object(), []
    monkeypatch.setattr(module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), url=url))
    def create(actual, **options):
        assert actual is url
        calls.append(options)
        return binding
    def sessions(**options):
        assert options == {"bind": binding, "autoflush": False, "expire_on_commit": False, "future": True}
        return "live-session-factory"
    monkeypatch.setattr(module, "create_engine", create)
    monkeypatch.setattr(module, "sessionmaker", sessions)
    assert module._session_factory.__wrapped__() == "live-session-factory"
    assert calls == [{"future": True, "pool_pre_ping": True, "pool_size": 4, "max_overflow": 0,
                      "pool_timeout": 5, "isolation_level": "READ COMMITTED"}]


def fake_session(monkeypatch, *, setup=None, rollback=None):
    calls = []
    def connect(**options):
        assert options == {"execution_options": {"isolation_level": "READ COMMITTED"}}
        calls.append("connect")
    def execute(statement):
        assert str(statement) == "SET TRANSACTION READ ONLY"
        assert module.current_source_access_read_session() is None
        calls.append("read-only")
        if setup:
            setup()
    def undo():
        calls.append("rollback")
        if rollback:
            rollback()
    session = SimpleNamespace(connection=connect, execute=execute, rollback=undo, close=lambda: calls.append("close"))
    monkeypatch.setattr(module, "_session_factory", lambda: lambda: session)
    return session, calls


def test_nested_live_reads_reuse_only_the_connection_and_end_the_scope(monkeypatch):
    session, calls = fake_session(monkeypatch)
    with module.live_source_access_read_session() as outer:
        assert outer is session and module.current_source_access_read_session() is session
        with module.live_source_access_read_session() as nested:
            assert nested is session
        assert module.current_source_access_read_session() is session
    assert calls == ["connect", "read-only", "rollback", "close"]
    assert module.current_source_access_read_session() is None


def test_failed_live_operation_closes_without_committing_or_retaining_permissions(monkeypatch):
    _, calls = fake_session(monkeypatch)
    with pytest.raises(ValueError, match="operation failed"):
        with module.live_source_access_read_session():
            raise ValueError("operation failed")
    assert calls == ["connect", "read-only", "rollback", "close"]
    assert module.current_source_access_read_session() is None


def test_copied_context_cannot_reopen_a_closed_transport(monkeypatch):
    _, calls = fake_session(monkeypatch)
    with module.live_source_access_read_session():
        delayed = copy_context()
    assert calls == ["connect", "read-only", "rollback", "close"]
    assert delayed.run(module.current_source_access_read_session) is None


def test_sibling_async_task_does_not_inherit_the_parent_connection(monkeypatch):
    session, calls = fake_session(monkeypatch)

    async def run():
        with module.live_source_access_read_session():
            async def sibling():
                assert module.current_source_access_read_session() is None
            await asyncio.create_task(sibling())
            assert module.current_source_access_read_session() is session

    asyncio.run(run())
    assert calls == ["connect", "read-only", "rollback", "close"]


@pytest.mark.parametrize("failure", ["setup", "capacity", "rollback"])
def test_live_read_failures_reset_context_and_close(monkeypatch, failure):
    def fail():
        if failure == "capacity":
            raise ConnectionPoolTimeout("private-database:credentials")
        raise RuntimeError("read-only setup failed" if failure == "setup" else "rollback failed")
    _, calls = fake_session(monkeypatch, setup=fail if failure in {"setup", "capacity"} else None,
                            rollback=fail if failure == "rollback" else None)
    expected = ImageArtifactUnavailable if failure == "capacity" else RuntimeError
    with pytest.raises(expected) as caught:
        with module.live_source_access_read_session():
            assert failure == "rollback"
    assert "private-database" not in str(caught.value) and "credentials" not in str(caught.value)
    assert calls[-2:] == ["rollback", "close"]
    assert module.current_source_access_read_session() is None
