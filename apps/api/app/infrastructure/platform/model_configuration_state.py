from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ...application.platform.model_settings import ModelProviderProfile, StudioSettings


class ModelConfigurationSettingsRepository(Protocol):
    def load(self) -> tuple[dict[str, Any], dict[str, str]]:
        ...


class ModelConfigurationSettingsGateway(Protocol):
    def build_model_profiles(
        self,
        *,
        model_preset: str,
        model_profiles: Mapping[str, ModelProviderProfile] | None = None,
    ) -> dict[str, ModelProviderProfile]:
        ...

    def build_settings(self, **kwargs: Any) -> StudioSettings:
        ...


@dataclass(frozen=True)
class ModelConfigurationStateAdapters:
    get_settings: Callable[[], StudioSettings]
    legacy_encrypted_api_keys: Callable[[], Mapping[str, str]]


class ProjectedModelConfigurationState:
    """Compatibility-only in-process model settings projection."""

    def __init__(self, adapters: ModelConfigurationStateAdapters) -> None:
        self._adapters = adapters

    def get_settings(self) -> StudioSettings:
        return self._adapters.get_settings()

    def legacy_encrypted_api_keys(self) -> Mapping[str, str]:
        return self._adapters.legacy_encrypted_api_keys()


class SQLAlchemyModelConfigurationState:
    """Rebuild base settings from PostgreSQL for every application request.

    This deliberately avoids a process-local settings cache. Model route
    activation can be changed by any API replica, so every replica must observe
    committed user preferences and legacy migration secrets immediately.
    """

    def __init__(
        self,
        repository: ModelConfigurationSettingsRepository,
        gateway: ModelConfigurationSettingsGateway,
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    def get_settings(self) -> StudioSettings:
        persisted, _ = self._repository.load()
        profiles = self._gateway.build_model_profiles(
            model_preset=persisted["model_preset"],
            model_profiles=persisted["model_profiles"],
        )
        return self._gateway.build_settings(
            language=persisted["language"],
            theme=persisted["theme"],
            notification_mode=persisted["notification_mode"],
            model_preset=profiles["chat"].model_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
        )

    def legacy_encrypted_api_keys(self) -> Mapping[str, str]:
        _, encrypted_keys = self._repository.load()
        return encrypted_keys


__all__ = [
    "ModelConfigurationSettingsGateway",
    "ModelConfigurationSettingsRepository",
    "ModelConfigurationStateAdapters",
    "ProjectedModelConfigurationState",
    "SQLAlchemyModelConfigurationState",
]
