from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


class ReadinessProbe(Protocol):
    """Infrastructure port used by the production readiness use case."""

    name: str

    def check(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    details: dict[str, str]


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    checks: dict[str, ReadinessCheck]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": {name: asdict(check) for name, check in self.checks.items()},
        }


class ReadinessApplicationService:
    """Aggregates mandatory infrastructure health without leaking adapters to HTTP."""

    def __init__(self, probes: tuple[ReadinessProbe, ...]) -> None:
        self._probes = probes

    def check(self) -> ReadinessReport:
        checks: dict[str, ReadinessCheck] = {}
        for probe in self._probes:
            try:
                checks[probe.name] = ReadinessCheck(status="ready", details=probe.check())
            except Exception as exc:
                checks[probe.name] = ReadinessCheck(
                    status="unavailable",
                    details={"reason": self._safe_reason(exc)},
                )
        status = "ready" if all(check.status == "ready" for check in checks.values()) else "unavailable"
        return ReadinessReport(status=status, checks=checks)

    @staticmethod
    def _safe_reason(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return message[:300]


__all__ = [
    "ReadinessApplicationService",
    "ReadinessCheck",
    "ReadinessProbe",
    "ReadinessReport",
]
