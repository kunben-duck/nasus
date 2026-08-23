from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator

from .account_models import UserProfile


@dataclass(frozen=True)
class ActorContext:
    """Request-scoped identity propagated through application use cases."""

    user: UserProfile
    request_id: str | None = None


_actor_context: ContextVar[ActorContext | None] = ContextVar(
    "nasus_actor_context",
    default=None,
)


def bind_actor(user: UserProfile, *, request_id: str | None = None) -> Token[ActorContext | None]:
    return _actor_context.set(ActorContext(user=user, request_id=request_id))


def reset_actor(token: Token[ActorContext | None]) -> None:
    _actor_context.reset(token)


def current_actor() -> ActorContext | None:
    return _actor_context.get()


def current_user(default: UserProfile | None = None) -> UserProfile:
    actor = current_actor()
    if actor is not None:
        return actor.user
    if default is None:
        raise RuntimeError("No authenticated actor is bound to the current execution context.")
    return default


@contextmanager
def actor_scope(user: UserProfile, *, request_id: str | None = None) -> Iterator[ActorContext]:
    token = bind_actor(user, request_id=request_id)
    try:
        actor = current_actor()
        if actor is None:  # pragma: no cover - ContextVar set/get invariant
            raise RuntimeError("Actor context could not be established.")
        yield actor
    finally:
        reset_actor(token)


__all__ = [
    "ActorContext",
    "actor_scope",
    "bind_actor",
    "current_actor",
    "current_user",
    "reset_actor",
]
