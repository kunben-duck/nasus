from __future__ import annotations

from typing import Any, Mapping, Protocol

from .model_config_test_grants import ModelConfigTestGrantRepositoryPort
from .model_settings import (
    ModelProviderProfile,
    ModelRouteSelection,
    SavedModelConfig,
    StudioSettings,
    StudioSettingsConnectionTestResponse,
)


class ModelConfigurationStatePort(Protocol):
    """Read persisted base settings and legacy secret metadata.

    Active model selections are assembled by the application service from the
    durable model configuration tables. Implementations must not treat an
    API-process cache as the source of truth.
    """

    def get_settings(self) -> StudioSettings:
        ...

    def legacy_encrypted_api_keys(self) -> Mapping[str, str]:
        ...


class ModelConfigurationRepositoryPort(Protocol):
    """Durable model configuration and route-selection facts."""

    def save(self, settings: StudioSettings, encrypted_custom_api_keys: dict[str, str]) -> None:
        ...

    def list_model_configs(self, route: str | None = None) -> list[SavedModelConfig]:
        ...

    def get_model_config(self, config_id: str) -> SavedModelConfig | None:
        ...

    def get_model_config_api_key_encrypted(self, config_id: str) -> str:
        ...

    def save_model_config(self, config: SavedModelConfig, api_key_encrypted: str) -> None:
        ...

    def list_model_route_selections(self) -> dict[str, ModelRouteSelection]:
        ...

    def get_model_route_selection(self, route: str) -> ModelRouteSelection | None:
        ...

    def save_model_route_selection(self, selection: ModelRouteSelection) -> None:
        ...


class ModelConfigurationSecretPort(Protocol):
    """Secret-at-rest boundary for provider API keys."""

    def encrypt_api_key(self, api_key: str) -> str:
        ...

    def decrypt_api_key(self, encrypted_value: str) -> str:
        ...

    def mask_api_key(self, api_key: str) -> str | None:
        ...


class ModelConfigurationGatewayPort(Protocol):
    """Provider-neutral model profile, settings and connectivity operations."""

    def build_settings(self, **kwargs: Any) -> StudioSettings:
        ...

    def build_model_profiles(
        self,
        *,
        model_preset: str,
        model_profiles: Mapping[str, ModelProviderProfile] | None = None,
    ) -> dict[str, ModelProviderProfile]:
        ...

    async def test_connection(
        self,
        *,
        settings: StudioSettings,
        route: str,
        custom_api_key: str,
    ) -> StudioSettingsConnectionTestResponse:
        ...


ModelConfigurationTestGrantPort = ModelConfigTestGrantRepositoryPort


__all__ = [
    "ModelConfigurationGatewayPort",
    "ModelConfigurationRepositoryPort",
    "ModelConfigurationSecretPort",
    "ModelConfigurationStatePort",
    "ModelConfigurationTestGrantPort",
]
