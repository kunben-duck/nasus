from __future__ import annotations

import hashlib
import json
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .model_configuration_ports import (
    ModelConfigurationGatewayPort,
    ModelConfigurationRepositoryPort,
    ModelConfigurationSecretPort,
    ModelConfigurationStatePort,
    ModelConfigurationTestGrantPort,
)
from .model_settings import (
    CustomModelConfig,
    ModelConfigCreateRequest,
    ModelConfigTestRequest,
    ModelConfigUpdateRequest,
    ModelProviderProfile,
    ModelRouteConfigurations,
    ModelRouteSelection,
    SavedModelConfig,
    StudioSettings,
    StudioSettingsConnectionTestRequest,
    StudioSettingsConnectionTestResponse,
    StudioSettingsPatch,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelConfigurationApplicationService:
    """Platform model and provider configuration use cases."""

    def __init__(
        self,
        *,
        state: ModelConfigurationStatePort,
        repository: ModelConfigurationRepositoryPort,
        secrets: ModelConfigurationSecretPort,
        gateway: ModelConfigurationGatewayPort,
        test_grants: ModelConfigurationTestGrantPort,
    ) -> None:
        self._state = state
        self._repository = repository
        self._secrets = secrets
        self._gateway = gateway
        self._test_grants = test_grants

    def get_settings(self) -> StudioSettings:
        current = self._state.get_settings()
        profiles = self.current_model_profiles()
        settings = self._gateway.build_settings(
            language=current.language,
            theme=current.theme,
            notification_mode=current.notification_mode,
            model_preset=profiles["chat"].model_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
            model_configurations=self.current_model_configurations(profiles),
        )
        chat_profile = profiles["chat"]
        return settings.model_copy(
            update={
                "model_preset": chat_profile.model_preset,
                "model_provider": chat_profile.model_provider,
                "model_name": chat_profile.model_name,
                "runtime_mode": chat_profile.runtime_mode,
                "fallback_provider": chat_profile.fallback_provider,
                "provider_statuses": chat_profile.provider_statuses,
                "active_provider_status": chat_profile.active_provider_status,
                "custom_model": chat_profile.custom_model,
                "model_profiles": profiles,
            }
        )

    def update_settings(self, payload: StudioSettingsPatch) -> StudioSettings:
        current = self._state.get_settings()
        language = payload.language or current.language
        theme = payload.theme or current.theme
        notification_mode = payload.notification_mode or current.notification_mode
        profiles = self.current_model_profiles()
        settings = self._gateway.build_settings(
            language=language,
            theme=theme,
            notification_mode=notification_mode,
            model_preset=profiles["chat"].model_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
            model_configurations=self.current_model_configurations(profiles),
        )
        self._repository.save(
            settings,
            dict(self._state.legacy_encrypted_api_keys()),
        )
        return self.get_settings()

    async def test_settings_connection(
        self,
        payload: Optional[StudioSettingsConnectionTestRequest] = None,
    ) -> StudioSettingsConnectionTestResponse:
        current = self._state.get_settings()
        # With no explicit override, probe the route selected in PostgreSQL.
        # Base settings no longer own the active model selection.
        request = payload or StudioSettingsConnectionTestRequest(model_route="chat")
        model_route = request.model_route or "chat"
        profiles = self.current_model_profiles()
        selection = self._repository.get_model_route_selection(model_route)
        active_config = (
            self._repository.get_model_config(selection.active_config_id)
            if selection
            and selection.active_source == "custom"
            and selection.active_config_id
            else None
        )
        has_model_override = any(
            value is not None
            for value in (
                request.model_preset,
                request.custom_provider_kind,
                request.custom_base_url,
                request.custom_model_name,
                request.custom_api_key,
            )
        )
        if active_config is not None and not has_model_override:
            # A failed persisted health result disables normal inference. An
            # explicit connection test must still be able to probe the saved
            # configuration so operators can restore the route.
            profiles[model_route] = self._profile_for_saved_config(active_config)
        profile = profiles[model_route]
        custom_model = profile.custom_model.model_copy(deep=True)
        if request.custom_provider_kind is not None:
            custom_model.provider_kind = request.custom_provider_kind
        if request.custom_base_url is not None:
            custom_model.base_url = request.custom_base_url.strip() or None
        if request.custom_model_name is not None:
            custom_model.model_name = request.custom_model_name.strip()

        custom_api_key = self.get_custom_model_api_key(model_route)
        if request.custom_api_key is not None:
            custom_api_key = request.custom_api_key.strip()
        custom_model.has_api_key = bool(custom_api_key)
        custom_model.api_key_masked = self._secrets.mask_api_key(custom_api_key)

        profile.model_preset = request.model_preset or profile.model_preset
        profile.custom_model = custom_model
        profiles[model_route] = profile
        settings = self._gateway.build_settings(
            language=current.language,
            theme=current.theme,
            notification_mode=current.notification_mode,
            model_preset=profiles["chat"].model_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
        )
        result = await self._gateway.test_connection(
            settings=settings,
            route=model_route,
            custom_api_key=custom_api_key,
        )
        if active_config is not None and not has_model_override:
            self._record_saved_model_connection_result(active_config, result)
        return result

    async def test_model_config_connection(self, payload: ModelConfigTestRequest) -> StudioSettingsConnectionTestResponse:
        try:
            raw_api_key = self._resolve_model_config_raw_api_key(payload)
        except RuntimeError:
            return StudioSettingsConnectionTestResponse(
                ok=False,
                model_route=payload.model_route,
                provider=payload.custom_provider_kind,
                model_name=payload.custom_model_name.strip(),
                runtime_mode="fallback",
                fallback_provider="mock",
                message="Saved API key could not be decrypted. Re-enter the API key, test again, and save the model.",
            )
        fingerprint = self._model_config_fingerprint(payload, raw_api_key)
        settings = self._settings_for_unsaved_model(payload, raw_api_key)
        result = await self._gateway.test_connection(
            settings=settings,
            route=payload.model_route,
            custom_api_key=raw_api_key,
        )
        result.fingerprint = fingerprint
        if result.ok:
            token = secrets.token_urlsafe(32)
            issued_at = datetime.now(timezone.utc)
            self._test_grants.purge_expired(
                now=issued_at
            )
            self._test_grants.issue(
                raw_token=token,
                route=payload.model_route,
                config_id=payload.config_id,
                fingerprint=fingerprint,
                issued_at=issued_at,
                expires_at=issued_at + timedelta(minutes=15),
            )
            result.test_token = token
        return result

    def create_model_config(self, payload: ModelConfigCreateRequest) -> StudioSettings:
        raw_api_key = self._resolve_model_config_raw_api_key(payload)
        fingerprint = self._model_config_fingerprint(payload, raw_api_key)
        if not self._test_grants.consume(
            raw_token=payload.test_token,
            route=payload.model_route,
            config_id=None,
            fingerprint=fingerprint,
            consumed_at=datetime.now(timezone.utc),
        ):
            raise ValueError("model configuration must be tested successfully before it can be saved")

        now = _now_iso()
        existing_count = len(self._repository.list_model_configs(payload.model_route))
        display_name = (payload.display_name or payload.custom_model_name).strip() or payload.custom_model_name.strip()
        config = SavedModelConfig(
            config_id=f"model_{uuid4().hex}",
            route=payload.model_route,
            display_name=display_name,
            provider_kind=payload.custom_provider_kind,
            base_url=payload.custom_base_url.strip().rstrip("/") if payload.custom_base_url else None,
            model_name=payload.custom_model_name.strip(),
            api_key_masked=self._secrets.mask_api_key(raw_api_key),
            last_tested_at=now,
            last_test_signature=fingerprint,
            last_test_result={"ok": True, "message": "Connection succeeded."},
            created_at=now,
            updated_at=now,
        )
        self._repository.save_model_config(
            config,
            self._secrets.encrypt_api_key(raw_api_key),
        )

        if existing_count == 0:
            self._repository.save_model_route_selection(
                ModelRouteSelection(
                    route=payload.model_route,
                    active_source="custom",
                    active_config_id=config.config_id,
                    updated_at=now,
                )
            )
        return self.get_settings()

    def update_model_config(self, config_id: str, payload: ModelConfigUpdateRequest) -> StudioSettings:
        existing = self._repository.get_model_config(config_id)
        if existing is None:
            raise KeyError(config_id)
        if payload.model_route != existing.route:
            raise ValueError("model route cannot be changed when editing an existing model configuration")

        display_name = (payload.display_name or payload.custom_model_name).strip() or payload.custom_model_name.strip()
        if self._is_display_name_only_model_config_update(existing, payload):
            encrypted_key = self._repository.get_model_config_api_key_encrypted(config_id)
            self._repository.save_model_config(
                existing.model_copy(update={"display_name": display_name, "updated_at": _now_iso()}),
                encrypted_key,
            )
            return self.get_settings()

        raw_api_key = self._resolve_model_config_raw_api_key(payload.model_copy(update={"config_id": config_id}))
        fingerprint = self._model_config_fingerprint(payload, raw_api_key)
        if not self._test_grants.consume(
            raw_token=payload.test_token,
            route=payload.model_route,
            config_id=config_id,
            fingerprint=fingerprint,
            consumed_at=datetime.now(timezone.utc),
        ):
            raise ValueError("model configuration must be tested successfully before it can be saved")

        now = _now_iso()
        config = existing.model_copy(
            update={
                "display_name": display_name,
                "provider_kind": payload.custom_provider_kind,
                "base_url": payload.custom_base_url.strip().rstrip("/") if payload.custom_base_url else None,
                "model_name": payload.custom_model_name.strip(),
                "api_key_masked": self._secrets.mask_api_key(raw_api_key),
                "last_tested_at": now,
                "last_test_signature": fingerprint,
                "last_test_result": {"ok": True, "message": "Connection succeeded."},
                "legacy_imported": False,
                "updated_at": now,
            }
        )
        self._repository.save_model_config(
            config,
            self._secrets.encrypt_api_key(raw_api_key),
        )
        return self.get_settings()

    def list_model_configurations(self, route: Optional[str] = None) -> Any:
        settings = self.get_settings()
        if route:
            return settings.model_configurations[route]
        return settings.model_configurations

    def activate_model_config(self, config_id: str) -> StudioSettings:
        config = self._repository.get_model_config(config_id)
        if config is None:
            raise KeyError(config_id)
        self._repository.save_model_route_selection(
            ModelRouteSelection(
                route=config.route,
                active_source="custom",
                active_config_id=config.config_id,
                updated_at=_now_iso(),
            )
        )
        return self.get_settings()

    def use_system_default_model_config(self, route: str) -> StudioSettings:
        self._repository.save_model_route_selection(
            ModelRouteSelection(
                route=route,  # type: ignore[arg-type]
                active_source="system_default",
                active_config_id=None,
                updated_at=_now_iso(),
            )
        )
        return self.get_settings()

    def current_model_profiles(self) -> Dict[str, ModelProviderProfile]:
        selections = self._repository.list_model_route_selections()
        configs = {
            config.config_id: config for config in self._repository.list_model_configs()
        }
        raw_profiles: Dict[str, ModelProviderProfile] = {}
        for route in ("chat", "embedding", "rerank"):
            selection = selections.get(route)
            active_config = configs.get(selection.active_config_id) if selection and selection.active_source == "custom" else None
            if active_config:
                raw_profiles[route] = ModelProviderProfile(
                    route=route,  # type: ignore[arg-type]
                    model_preset="custom",
                    custom_model=CustomModelConfig(
                        provider_kind=active_config.provider_kind,
                        base_url=active_config.base_url,
                        model_name=active_config.model_name,
                        has_api_key=bool(active_config.api_key_masked),
                        api_key_masked=active_config.api_key_masked,
                    ),
                )
            else:
                raw_profiles[route] = ModelProviderProfile(route=route)  # type: ignore[arg-type]
        profiles = self._gateway.build_model_profiles(
            model_preset=raw_profiles["chat"].model_preset,
            model_profiles=raw_profiles,
        )
        for route in ("chat", "embedding", "rerank"):
            selection = selections.get(route)
            active_config = (
                configs.get(selection.active_config_id)
                if selection and selection.active_source == "custom"
                else None
            )
            if active_config is None:
                continue
            last_test_ok = active_config.last_test_result.get("ok") is True
            if last_test_ok and not active_config.legacy_imported:
                continue
            reason = str(
                active_config.last_test_result.get("message")
                or (
                    "Legacy imported model must be tested successfully before use."
                    if active_config.legacy_imported
                    else "Saved model has not passed a connection test."
                )
            )
            active_status = profiles[route].active_provider_status.model_copy(
                update={
                    "available": False,
                    "mode": "fallback",
                    "fallback_provider": "mock",
                    "reason": reason,
                }
            )
            profiles[route] = profiles[route].model_copy(
                update={
                    "runtime_mode": "fallback",
                    "fallback_provider": "mock",
                    "active_provider_status": active_status,
                }
            )
        return profiles

    def current_model_configurations(
        self,
        model_profiles: Optional[Dict[str, ModelProviderProfile]] = None,
    ) -> Dict[str, ModelRouteConfigurations]:
        profiles = model_profiles or self.current_model_profiles()
        selections = self._repository.list_model_route_selections()
        saved_configs = self._repository.list_model_configs()
        saved_by_route: Dict[str, List[SavedModelConfig]] = defaultdict(list)
        for config in saved_configs:
            saved_by_route[config.route].append(config)

        configurations: Dict[str, ModelRouteConfigurations] = {}
        system_profiles = self._gateway.build_model_profiles(
            model_preset="system_default"
        )
        for route in ("chat", "embedding", "rerank"):
            selection = selections.get(route) or ModelRouteSelection(route=route, updated_at="")  # type: ignore[arg-type]
            route_configs = []
            for config in sorted(saved_by_route.get(route, []), key=lambda item: item.created_at):
                active = selection.active_source == "custom" and selection.active_config_id == config.config_id
                runtime_profile = profiles[route] if active else self._profile_for_saved_config(config)
                route_configs.append(
                    config.model_copy(
                        update={
                            "active": active,
                            "runtime_mode": runtime_profile.runtime_mode,
                            "last_test_result": config.last_test_result or runtime_profile.active_provider_status.model_dump(),
                        }
                    )
                )
            configurations[route] = ModelRouteConfigurations(
                route=route,  # type: ignore[arg-type]
                active_source=selection.active_source,
                active_config_id=selection.active_config_id,
                system_default=system_profiles[route],
                configurations=route_configs,
            )
        return configurations

    def migrate_legacy_model_configs_if_needed(self, persisted_settings: Dict[str, Any], persisted_custom_keys: Dict[str, str]) -> None:
        if self._repository.list_model_configs():
            return
        legacy_profiles = persisted_settings.get("model_profiles") or {}
        for route in ("chat", "embedding", "rerank"):
            profile = legacy_profiles.get(route)
            if not profile or profile.model_preset != "custom":
                continue
            encrypted_key = persisted_custom_keys.get(route)
            if not encrypted_key:
                continue
            custom = profile.custom_model
            now = _now_iso()
            config = SavedModelConfig(
                config_id=f"legacy_{route}_{uuid4().hex}",
                route=route,  # type: ignore[arg-type]
                display_name=f"Legacy {route} model",
                provider_kind=custom.provider_kind,
                base_url=custom.base_url,
                model_name=custom.model_name,
                api_key_masked=custom.api_key_masked,
                last_tested_at=now,
                last_test_signature="legacy-imported",
                last_test_result={"ok": True, "message": "Legacy imported model; retest before editing."},
                legacy_imported=True,
                created_at=now,
                updated_at=now,
            )
            self._repository.save_model_config(config, encrypted_key)
            self._repository.save_model_route_selection(
                ModelRouteSelection(route=route, active_source="custom", active_config_id=config.config_id, updated_at=now)  # type: ignore[arg-type]
            )

    def get_custom_model_api_key(self, model_route: str = "chat") -> str:
        selection = self._repository.get_model_route_selection(model_route)
        if selection and selection.active_source == "custom" and selection.active_config_id:
            encrypted = self._repository.get_model_config_api_key_encrypted(
                selection.active_config_id
            )
        else:
            encrypted = self._state.legacy_encrypted_api_keys().get(model_route, "")
        try:
            return self._secrets.decrypt_api_key(encrypted)
        except RuntimeError:
            return ""

    def _profile_for_saved_config(self, config: SavedModelConfig) -> ModelProviderProfile:
        return self._gateway.build_model_profiles(
            model_preset="system_default",
            model_profiles={
                config.route: ModelProviderProfile(
                    route=config.route,
                    model_preset="custom",
                    custom_model=CustomModelConfig(
                        provider_kind=config.provider_kind,
                        base_url=config.base_url,
                        model_name=config.model_name,
                        has_api_key=bool(config.api_key_masked),
                        api_key_masked=config.api_key_masked,
                    ),
                )
            },
        )[config.route]

    def _record_saved_model_connection_result(
        self,
        config: SavedModelConfig,
        result: StudioSettingsConnectionTestResponse,
    ) -> None:
        now = _now_iso()
        encrypted_key = self._repository.get_model_config_api_key_encrypted(
            config.config_id
        )
        updated = config.model_copy(
            update={
                "last_tested_at": now,
                "last_test_result": {
                    "ok": result.ok,
                    "message": result.message,
                    "runtime_mode": result.runtime_mode,
                    "provider": result.provider,
                    "model_name": result.model_name,
                    "latency_ms": result.latency_ms,
                },
                "legacy_imported": False if result.ok else config.legacy_imported,
                "updated_at": now,
            }
        )
        self._repository.save_model_config(updated, encrypted_key)

    def _settings_for_unsaved_model(self, payload: ModelConfigTestRequest, raw_api_key: str) -> StudioSettings:
        profiles = self.current_model_profiles()
        profiles[payload.model_route] = ModelProviderProfile(
            route=payload.model_route,
            model_preset="custom",
            custom_model=CustomModelConfig(
                provider_kind=payload.custom_provider_kind,
                base_url=payload.custom_base_url.strip().rstrip("/") if payload.custom_base_url else None,
                model_name=payload.custom_model_name.strip(),
                has_api_key=bool(raw_api_key),
                api_key_masked=self._secrets.mask_api_key(raw_api_key),
            ),
        )
        current = self._state.get_settings()
        return self._gateway.build_settings(
            language=current.language,
            theme=current.theme,
            notification_mode=current.notification_mode,
            model_preset=profiles["chat"].model_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
            model_configurations=self.current_model_configurations(profiles),
        )

    def _resolve_model_config_raw_api_key(self, payload: ModelConfigTestRequest) -> str:
        raw_api_key = payload.custom_api_key.strip()
        if raw_api_key or not payload.config_id:
            return raw_api_key
        existing = self._repository.get_model_config(payload.config_id)
        if existing is None or existing.route != payload.model_route:
            return ""
        encrypted = self._repository.get_model_config_api_key_encrypted(payload.config_id)
        return self._secrets.decrypt_api_key(encrypted) if encrypted else ""

    @staticmethod
    def _model_config_fingerprint(payload: ModelConfigTestRequest, raw_api_key: str) -> str:
        normalized = {
            "route": payload.model_route,
            "provider_kind": payload.custom_provider_kind,
            "base_url": (payload.custom_base_url or "").strip().rstrip("/"),
            "model_name": payload.custom_model_name.strip(),
            "api_key_sha256": hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest(),
        }
        return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _is_display_name_only_model_config_update(existing: SavedModelConfig, payload: ModelConfigUpdateRequest) -> bool:
        display_name = (payload.display_name or payload.custom_model_name).strip() or payload.custom_model_name.strip()
        return (
            display_name != existing.display_name
            and payload.model_route == existing.route
            and payload.custom_provider_kind == existing.provider_kind
            and (payload.custom_base_url or "").strip().rstrip("/") == (existing.base_url or "")
            and payload.custom_model_name.strip() == existing.model_name
            and not payload.custom_api_key.strip()
        )
