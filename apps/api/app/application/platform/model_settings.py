from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ModelRoute = Literal["chat", "embedding", "rerank"]
ProviderName = Literal["mock", "openai", "gemini", "anthropic", "openai_compatible"]
ModelPreset = Literal["system_default", "custom"]
CustomProviderKind = Literal["openai_compatible", "openai", "gemini", "anthropic"]
ModelRouteSelectionSource = Literal["system_default", "custom"]


class ProviderStatus(BaseModel):
    provider: ProviderName
    available: bool
    configured_via: Literal["builtin", "system_default", "custom"]
    mode: Literal["live", "fallback"] = "fallback"
    fallback_provider: Optional[Literal["mock"]] = None
    reason: str


class CustomModelConfig(BaseModel):
    provider_kind: CustomProviderKind = "openai_compatible"
    base_url: Optional[str] = None
    model_name: str = ""
    has_api_key: bool = False
    api_key_masked: Optional[str] = None


class ModelProviderProfile(BaseModel):
    route: ModelRoute
    model_preset: ModelPreset = "system_default"
    model_provider: ProviderName = "openai"
    model_name: str = ""
    runtime_mode: Literal["live", "fallback"] = "fallback"
    fallback_provider: Literal["mock"] = "mock"
    provider_statuses: List[ProviderStatus] = Field(default_factory=list)
    active_provider_status: ProviderStatus = Field(
        default_factory=lambda: ProviderStatus(
            provider="openai",
            available=False,
            configured_via="system_default",
            mode="fallback",
            fallback_provider="mock",
            reason="System default provider is not configured.",
        )
    )
    custom_model: CustomModelConfig = Field(default_factory=CustomModelConfig)


class SavedModelConfig(BaseModel):
    config_id: str
    route: ModelRoute
    display_name: str
    provider_kind: CustomProviderKind
    base_url: Optional[str] = None
    model_name: str
    api_key_masked: Optional[str] = None
    last_tested_at: str
    last_test_signature: str
    last_test_result: Dict[str, Any] = Field(default_factory=dict)
    runtime_mode: Literal["live", "fallback"] = "fallback"
    active: bool = False
    legacy_imported: bool = False
    created_at: str
    updated_at: str


class ModelRouteSelection(BaseModel):
    route: ModelRoute
    active_source: ModelRouteSelectionSource = "system_default"
    active_config_id: Optional[str] = None
    updated_at: str = ""


class ModelRouteConfigurations(BaseModel):
    route: ModelRoute
    active_source: ModelRouteSelectionSource = "system_default"
    active_config_id: Optional[str] = None
    system_default: ModelProviderProfile
    configurations: List[SavedModelConfig] = Field(default_factory=list)


class ModelConfigTestRequest(BaseModel):
    config_id: Optional[str] = None
    model_route: ModelRoute
    display_name: Optional[str] = None
    custom_provider_kind: CustomProviderKind = "openai_compatible"
    custom_base_url: Optional[str] = None
    custom_model_name: str
    custom_api_key: str = ""


class ModelConfigCreateRequest(ModelConfigTestRequest):
    test_token: str


class ModelConfigUpdateRequest(ModelConfigCreateRequest):
    pass


class StudioSettings(BaseModel):
    language: Literal["en", "zh"] = "en"
    theme: Literal["dark", "light", "system"] = "dark"
    model_preset: ModelPreset = "system_default"
    notification_mode: Literal["important", "all", "muted"] = "important"
    model_provider: ProviderName = "openai"
    model_name: str = "gpt-5.4"
    runtime_mode: Literal["live", "fallback"] = "fallback"
    fallback_provider: Literal["mock"] = "mock"
    provider_statuses: List[ProviderStatus] = Field(default_factory=list)
    active_provider_status: ProviderStatus = Field(
        default_factory=lambda: ProviderStatus(
            provider="openai",
            available=False,
            configured_via="system_default",
            mode="fallback",
            fallback_provider="mock",
            reason="System default provider is not configured.",
        )
    )
    custom_model: CustomModelConfig = Field(default_factory=CustomModelConfig)
    model_profiles: Dict[ModelRoute, ModelProviderProfile] = Field(default_factory=dict)
    model_configurations: Dict[ModelRoute, ModelRouteConfigurations] = Field(default_factory=dict)


class StudioSettingsPatch(BaseModel):
    language: Optional[Literal["en", "zh"]] = None
    theme: Optional[Literal["dark", "light", "system"]] = None
    model_route: Optional[ModelRoute] = None
    model_preset: Optional[ModelPreset] = None
    notification_mode: Optional[Literal["important", "all", "muted"]] = None
    custom_provider_kind: Optional[CustomProviderKind] = None
    custom_base_url: Optional[str] = None
    custom_model_name: Optional[str] = None
    custom_api_key: Optional[str] = None


class StudioSettingsConnectionTestRequest(BaseModel):
    model_route: Optional[ModelRoute] = None
    model_preset: Optional[ModelPreset] = None
    custom_provider_kind: Optional[CustomProviderKind] = None
    custom_base_url: Optional[str] = None
    custom_model_name: Optional[str] = None
    custom_api_key: Optional[str] = None


class StudioSettingsConnectionTestResponse(BaseModel):
    ok: bool
    model_route: ModelRoute = "chat"
    provider: ProviderName
    model_name: str
    runtime_mode: Literal["live", "fallback"]
    fallback_provider: Optional[Literal["mock"]] = None
    latency_ms: Optional[int] = None
    message: str
    test_token: Optional[str] = None
    fingerprint: Optional[str] = None


__all__ = [
    "CustomModelConfig",
    "CustomProviderKind",
    "ModelConfigCreateRequest",
    "ModelConfigTestRequest",
    "ModelConfigUpdateRequest",
    "ModelPreset",
    "ModelProviderProfile",
    "ModelRoute",
    "ModelRouteConfigurations",
    "ModelRouteSelection",
    "ModelRouteSelectionSource",
    "ProviderName",
    "ProviderStatus",
    "SavedModelConfig",
    "StudioSettings",
    "StudioSettingsConnectionTestRequest",
    "StudioSettingsConnectionTestResponse",
    "StudioSettingsPatch",
]
