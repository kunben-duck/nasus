from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.image_revision import ImageArtifactUnavailable
from apps.api.app.infrastructure.persistence import image_read_snapshot as module


def test_non_postgresql_snapshot_refuses_to_create_a_fallback_engine(monkeypatch):
    monkeypatch.setattr(module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))

    def forbidden(*args, **kwargs):
        pytest.fail("No fallback connection may be created")

    monkeypatch.setattr(module, "create_engine", forbidden)
    with pytest.raises(ImageArtifactUnavailable, match="PostgreSQL"):
        module._session_factory.__wrapped__()


def test_snapshot_pool_uses_the_authoritative_database_and_finite_capacity(monkeypatch):
    marker = object()
    binding = object()
    calls = []
    monkeypatch.setattr(module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), url=marker))

    def create(url, **options):
        assert url is marker
        calls.append(options)
        return binding

    def sessions(**options):
        assert options["bind"] is binding and options["autoflush"] is False
        assert options["expire_on_commit"] is False
        return "snapshot-session-factory"

    monkeypatch.setattr(module, "create_engine", create)
    monkeypatch.setattr(module, "sessionmaker", sessions)
    assert module._session_factory.__wrapped__() == "snapshot-session-factory"
    assert calls == [{"future": True, "pool_pre_ping": True, "pool_size": 4,
        "max_overflow": 0, "pool_timeout": 5, "isolation_level": "REPEATABLE READ"}]


def test_snapshot_closes_even_if_rollback_fails(monkeypatch):
    calls = []

    def rollback():
        calls.append("rollback")
        raise RuntimeError("rollback unavailable")

    session = SimpleNamespace(connection=lambda **kwargs: None, execute=lambda statement: None,
        rollback=rollback, close=lambda: calls.append("close"))
    monkeypatch.setattr(module, "_session_factory", lambda: lambda: session)
    with pytest.raises(RuntimeError, match="rollback unavailable"):
        with module.image_read_snapshot_scope() as actual:
            assert actual is session
    assert calls == ["rollback", "close"]


def test_snapshot_body_failure_rolls_back_without_commit(monkeypatch):
    calls = []
    session = SimpleNamespace(connection=lambda **kwargs: None, execute=lambda statement: None,
        rollback=lambda: calls.append("rollback"), close=lambda: calls.append("close"))
    monkeypatch.setattr(module, "_session_factory", lambda: lambda: session)
    with pytest.raises(ValueError, match="compilation failed"):
        with module.image_read_snapshot_scope():
            raise ValueError("compilation failed")
    assert calls == ["rollback", "close"]


def test_snapshot_is_not_exposed_until_read_only_setup_succeeds(monkeypatch):
    calls = []
    def execute(statement):
        assert str(statement) == "SET TRANSACTION READ ONLY"
        assert module.current_image_read_snapshot() is None
        raise RuntimeError("read-only setup failed")
    session = SimpleNamespace(connection=lambda **kwargs: None, execute=execute,
        rollback=lambda: calls.append("rollback"), close=lambda: calls.append("close"))
    monkeypatch.setattr(module, "_session_factory", lambda: lambda: session)
    with pytest.raises(RuntimeError, match="read-only setup failed"):
        with module.image_read_snapshot_scope():
            pytest.fail("Unsafe snapshot must not be visible")
    assert calls == ["rollback", "close"] and module.current_image_read_snapshot() is None
