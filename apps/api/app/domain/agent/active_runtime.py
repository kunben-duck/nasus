"""Persisted active intervals; legacy goals keep their original wall clock."""
from datetime import datetime, timezone


MAX_RUNTIME_MS = 2**63 - 1


def validate_active_clock(runtime_ms, started_at):
    if runtime_ms is None:
        if started_at is not None:
            raise ValueError("An active interval requires a persisted runtime counter.")
        return
    if type(runtime_ms) is not int or not 0 <= runtime_ms <= MAX_RUNTIME_MS:
        raise ValueError("Invalid active runtime counter.")
    if started_at is not None:
        if type(started_at) is not str or len(started_at) > 128:
            raise ValueError("Invalid active interval timestamp.")
        _timestamp(started_at)


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid active interval timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("An active interval must have an explicit timezone.")
    return parsed


def _now(now):
    current = now or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def active_runtime_used_ms(goal, *, now=None):
    runtime_ms = getattr(goal, "active_runtime_ms", None)
    started_at = getattr(goal, "active_started_at", None)
    validate_active_clock(runtime_ms, started_at)
    if runtime_ms is None:
        return None
    if started_at is not None:
        elapsed = _now(now) - _timestamp(started_at)
        microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
        runtime_ms += max(0, microseconds // 1000)
    validate_active_clock(runtime_ms, None)
    return runtime_ms


def begin_active_runtime(goal, *, now=None):
    validate_active_clock(getattr(goal, "active_runtime_ms", None), getattr(goal, "active_started_at", None))
    if getattr(goal, "active_runtime_ms", None) is not None and goal.active_started_at is None:
        goal.active_started_at = _now(now).isoformat()


def settle_active_runtime(goal, *, now=None):
    runtime_ms = active_runtime_used_ms(goal, now=now)
    if runtime_ms is not None:
        goal.active_runtime_ms = runtime_ms
        goal.active_started_at = None
