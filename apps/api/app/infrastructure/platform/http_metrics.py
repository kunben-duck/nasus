from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


LOGGER = logging.getLogger("nasus.http")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.propagate = False


class HttpMetrics:
    """Low-cardinality Prometheus metrics and structured request logging."""

    def __init__(self, collectors: Iterable[Any] = ()) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "nasus_http_requests_total",
            "HTTP requests completed by the Nasus API.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "nasus_http_request_duration_seconds",
            "Nasus API request latency.",
            ("method", "route"),
            registry=self.registry,
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
        )
        self.in_progress = Gauge(
            "nasus_http_requests_in_progress",
            "Nasus API requests currently in progress.",
            registry=self.registry,
        )
        self.rate_limit_rejections = Counter(
            "nasus_rate_limit_rejections_total",
            "Requests rejected by the platform rate limiter.",
            ("scope",),
            registry=self.registry,
        )
        for collector in collectors:
            self.registry.register(collector)

    def observe(
        self,
        *,
        request_id: str,
        method: str,
        route: str,
        path: str,
        status_code: int,
        duration_seconds: float,
        user_id: str | None,
    ) -> None:
        self.requests.labels(method, route, str(status_code)).inc()
        self.duration.labels(method, route).observe(duration_seconds)
        LOGGER.info(
            json.dumps(
                {
                    "event": "http.request.completed",
                    "request_id": request_id,
                    "method": method,
                    "route": route,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 3),
                    "user_id": user_id,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)

    @staticmethod
    def route_label(request: Any) -> str:
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        return str(path) if path else "unmatched"


__all__ = ["HttpMetrics"]
