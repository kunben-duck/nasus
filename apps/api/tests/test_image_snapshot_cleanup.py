"""Proof-cache cleanup cannot suppress release of an owned read connection."""
from types import SimpleNamespace

import pytest

from apps.api.app.infrastructure.persistence import image_read_snapshot as module


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_proof_cache_cleanup_failure_still_resets_scope_rolls_back_and_closes(monkeypatch, rollback_fails):
    calls = []

    class BrokenCache:
        def pop(self, key, default):
            assert key == module.CONTEXT_PROVENANCE_CACHE and default is None
            assert module.current_image_read_snapshot() is None
            calls.append("clear")
            raise ValueError("proof-cache cleanup failed")

    def rollback():
        calls.append("rollback")
        if rollback_fails:
            raise RuntimeError("rollback unavailable")

    session = SimpleNamespace(info=BrokenCache(), connection=lambda **kwargs: None,
        execute=lambda statement: None, rollback=rollback, close=lambda: calls.append("close"))
    monkeypatch.setattr(module, "_session_factory", lambda: lambda: session)
    with pytest.raises(RuntimeError if rollback_fails else ValueError):
        with module.image_read_snapshot_scope() as actual:
            assert actual is session and module.current_image_read_snapshot()[0] is session
    assert calls == ["clear", "rollback", "close"] and module.current_image_read_snapshot() is None


def test_successful_proof_cache_cleanup_does_not_keep_private_anchors(monkeypatch):
    calls, private = [], {module.CONTEXT_PROVENANCE_CACHE: {"original-context": "original-hash"}, "other": "untouched"}
    session = SimpleNamespace(info=private, connection=lambda **kwargs: None, execute=lambda statement: None,
        rollback=lambda: calls.append("rollback"), close=lambda: calls.append("close"))
    monkeypatch.setattr(module, "_session_factory", lambda: lambda: session)
    with module.image_read_snapshot_scope():
        assert module.CONTEXT_PROVENANCE_CACHE in private
    assert private == {"other": "untouched"} and calls == ["rollback", "close"]
    assert module.current_image_read_snapshot() is None
