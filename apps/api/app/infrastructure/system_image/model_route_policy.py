from __future__ import annotations

from typing import Any


class SystemImageModelRouteUnavailableError(RuntimeError):
    """Raised when a production system-image model route degrades."""

    def __init__(self, route: str, result: Any) -> None:
        provider = str(getattr(result, "provider", "unknown"))
        model_name = str(getattr(result, "model_name", "unknown"))
        reason = str(getattr(result, "reason", "provider result was not live"))
        super().__init__(
            f"System-image {route} route must be live in production; "
            f"received {provider}:{model_name} fallback ({reason})."
        )
        self.route = route
        self.provider = provider
        self.model_name = model_name
        self.reason = reason


def require_live_system_image_result(route: str, result: Any) -> Any:
    if getattr(result, "mode", None) != "live":
        raise SystemImageModelRouteUnavailableError(route, result)
    return result


__all__ = [
    "SystemImageModelRouteUnavailableError",
    "require_live_system_image_result",
]
