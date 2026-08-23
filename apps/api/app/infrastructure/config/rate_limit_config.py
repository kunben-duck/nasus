from __future__ import annotations

from dataclasses import dataclass
import os


FALSE_VALUES = {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool
    backend: str
    window_seconds: int
    auth_limit: int
    agent_limit: int
    api_limit: int

    @classmethod
    def from_env(cls) -> "RateLimitConfig":
        return cls(
            enabled=os.getenv("NASUS_RATE_LIMIT_ENABLED", "false").strip().lower()
            not in FALSE_VALUES,
            backend=os.getenv("NASUS_RATE_LIMIT_BACKEND", "postgres").strip().lower()
            or "postgres",
            window_seconds=_positive_int("NASUS_RATE_LIMIT_WINDOW_SECONDS", 60),
            auth_limit=_positive_int("NASUS_RATE_LIMIT_AUTH_PER_WINDOW", 10),
            agent_limit=_positive_int("NASUS_RATE_LIMIT_AGENT_PER_WINDOW", 30),
            api_limit=_positive_int("NASUS_RATE_LIMIT_API_PER_WINDOW", 120),
        )

    def limit_for(self, scope: str) -> int:
        if scope == "auth":
            return self.auth_limit
        if scope == "agent":
            return self.agent_limit
        return self.api_limit


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


__all__ = ["RateLimitConfig"]
