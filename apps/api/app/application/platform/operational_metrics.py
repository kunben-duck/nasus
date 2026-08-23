from __future__ import annotations

from typing import Protocol


class OperationalMetricsExportPort(Protocol):
    def render(self) -> bytes: ...


__all__ = ["OperationalMetricsExportPort"]
