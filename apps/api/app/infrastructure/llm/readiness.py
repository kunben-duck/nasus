from __future__ import annotations

from typing import Callable

from ...application.platform.prompts import PromptRegistryPort
from ...application.platform.model_settings import ModelRoute, StudioSettings
from ...domain.platform.prompt_registry import BUILTIN_PROMPTS


SettingsProvider = Callable[[], StudioSettings]
MODEL_ROUTES: tuple[ModelRoute, ...] = ("chat", "embedding", "rerank")


class ModelRoutesReadinessProbe:
    """Verify that every model route resolves to a usable runtime profile."""

    name = "model_routes"

    def __init__(self, settings_provider: SettingsProvider, *, require_live: bool) -> None:
        self._settings_provider = settings_provider
        self._require_live = require_live

    def check(self) -> dict[str, str]:
        settings = self._settings_provider()
        missing = [route for route in MODEL_ROUTES if route not in settings.model_profiles]
        if missing:
            raise RuntimeError(f"model route profiles are missing: {', '.join(missing)}")

        details = {
            route: (
                f"{settings.model_profiles[route].runtime_mode}:"
                f"{settings.model_profiles[route].model_provider}:"
                f"{settings.model_profiles[route].model_name or 'unconfigured'}"
            )
            for route in MODEL_ROUTES
        }
        non_live = [
            route
            for route in MODEL_ROUTES
            if settings.model_profiles[route].runtime_mode != "live"
        ]
        if self._require_live and non_live:
            raise RuntimeError(
                "production model routes are not live: " + ", ".join(non_live)
            )
        return {
            "backend": "live" if not non_live else "development_fallback",
            **details,
        }


class PromptRegistryReadinessProbe:
    """Require an active immutable version for every runtime prompt contract."""

    name = "prompt_registry"

    def __init__(self, registry: PromptRegistryPort) -> None:
        self._registry = registry

    def check(self) -> dict[str, str]:
        active_versions: list[str] = []
        for definition in BUILTIN_PROMPTS:
            active = self._registry.get_active(definition.prompt_id)
            if not active.system_template.strip():
                raise RuntimeError(
                    f"active prompt {active.prompt_id}@{active.version} has no template"
                )
            active_versions.append(f"{active.prompt_id}@{active.version}")
        return {
            "backend": "postgresql",
            "active_count": str(len(active_versions)),
            "active_versions": ",".join(active_versions),
        }


__all__ = ["ModelRoutesReadinessProbe", "PromptRegistryReadinessProbe"]
