from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator


TurnStreamEmitter = Callable[[dict[str, Any]], None]

_turn_stream_emitter: ContextVar[TurnStreamEmitter | None] = ContextVar(
    "nasus_turn_stream_emitter",
    default=None,
)


def current_turn_stream_emitter() -> TurnStreamEmitter | None:
    return _turn_stream_emitter.get()


@contextmanager
def turn_stream_scope(emitter: TurnStreamEmitter) -> Iterator[None]:
    token = _turn_stream_emitter.set(emitter)
    try:
        yield
    finally:
        _turn_stream_emitter.reset(token)


__all__ = ["current_turn_stream_emitter", "turn_stream_scope"]
