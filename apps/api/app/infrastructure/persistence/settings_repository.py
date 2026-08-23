from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .db_models import ModelProviderConfigRecord, ModelRouteSelectionRecord, SettingsRecord
from .unit_of_work import session_scope
from ...application.platform.model_settings import (
    CustomModelConfig,
    ModelProviderProfile,
    ModelRouteSelection,
    SavedModelConfig,
    StudioSettings,
)


class SettingsRepository:
    def load(self) -> tuple[dict[str, Any], dict[str, str]]:
        with session_scope() as session:
            record = session.get(SettingsRecord, 1)
            if record is None:
                return self._defaults(), {}

            custom = record.custom_model or {}
            encrypted_keys = custom.get("_model_profile_api_keys_encrypted") or {}
            legacy_secret = record.custom_api_key_encrypted or ""
            if legacy_secret and "chat" not in encrypted_keys:
                encrypted_keys["chat"] = legacy_secret
            loaded = {
                "language": record.language,
                "theme": record.theme,
                "notification_mode": record.notification_mode,
                "model_preset": record.model_preset,
                "custom_model": {
                    "provider_kind": custom.get("provider_kind", "openai_compatible"),
                    "base_url": custom.get("base_url"),
                    "model_name": custom.get("model_name", ""),
                    "has_api_key": bool(encrypted_keys.get("chat")),
                    "api_key_masked": custom.get("api_key_masked"),
                },
                "model_profiles": self._load_profiles(custom.get("model_profiles") or {}, encrypted_keys, custom),
            }
            return loaded, encrypted_keys

    def save(self, settings: StudioSettings, encrypted_custom_api_keys: dict[str, str]) -> None:
        with session_scope() as session:
            record = session.get(SettingsRecord, 1)
            if record is None:
                record = SettingsRecord(settings_id=1)
                session.add(record)

            record.language = settings.language
            record.theme = settings.theme
            record.notification_mode = settings.notification_mode
            record.model_preset = settings.model_preset
            record.custom_model = {
                "provider_kind": settings.custom_model.provider_kind,
                "base_url": settings.custom_model.base_url,
                "model_name": settings.custom_model.model_name,
                "api_key_masked": settings.custom_model.api_key_masked,
                "model_profiles": {
                    route: {
                        "route": profile.route,
                        "model_preset": profile.model_preset,
                        "custom_model": {
                            "provider_kind": profile.custom_model.provider_kind,
                            "base_url": profile.custom_model.base_url,
                            "model_name": profile.custom_model.model_name,
                            "api_key_masked": profile.custom_model.api_key_masked,
                        },
                    }
                    for route, profile in settings.model_profiles.items()
                },
                "_model_profile_api_keys_encrypted": {
                    key: value for key, value in encrypted_custom_api_keys.items() if value
                },
            }
            record.custom_api_key_encrypted = encrypted_custom_api_keys.get("chat") or None

    def list_model_configs(self, route: str | None = None) -> list[SavedModelConfig]:
        with session_scope() as session:
            statement = select(ModelProviderConfigRecord)
            if route:
                statement = statement.where(ModelProviderConfigRecord.route == route)
            rows = session.scalars(statement).all()
        return [self._to_model_config(row) for row in rows]

    def get_model_config(self, config_id: str) -> SavedModelConfig | None:
        with session_scope() as session:
            row = session.get(ModelProviderConfigRecord, config_id)
        return self._to_model_config(row) if row else None

    def get_model_config_api_key_encrypted(self, config_id: str) -> str:
        with session_scope() as session:
            row = session.get(ModelProviderConfigRecord, config_id)
            return row.api_key_encrypted if row else ""

    def save_model_config(self, config: SavedModelConfig, api_key_encrypted: str) -> None:
        with session_scope() as session:
            row = session.get(ModelProviderConfigRecord, config.config_id)
            if row is None:
                row = ModelProviderConfigRecord(config_id=config.config_id)
                session.add(row)
                row.created_at = config.created_at
            row.route = config.route
            row.display_name = config.display_name
            row.provider_kind = config.provider_kind
            row.base_url = config.base_url
            row.model_name = config.model_name
            row.api_key_encrypted = api_key_encrypted
            row.api_key_masked = config.api_key_masked
            row.last_tested_at = config.last_tested_at
            row.last_test_signature = config.last_test_signature
            row.last_test_result = config.last_test_result
            row.legacy_imported = config.legacy_imported
            row.updated_at = config.updated_at

    def list_model_route_selections(self) -> dict[str, ModelRouteSelection]:
        with session_scope() as session:
            rows = session.scalars(select(ModelRouteSelectionRecord)).all()
        return {row.route: self._to_model_route_selection(row) for row in rows}

    def get_model_route_selection(self, route: str) -> ModelRouteSelection | None:
        with session_scope() as session:
            row = session.get(ModelRouteSelectionRecord, route)
        return self._to_model_route_selection(row) if row else None

    def save_model_route_selection(self, selection: ModelRouteSelection) -> None:
        with session_scope() as session:
            row = session.get(ModelRouteSelectionRecord, selection.route)
            if row is None:
                row = ModelRouteSelectionRecord(route=selection.route)
                session.add(row)
            row.active_source = selection.active_source
            row.active_config_id = selection.active_config_id
            row.updated_at = selection.updated_at

    @staticmethod
    def _to_model_config(row: ModelProviderConfigRecord) -> SavedModelConfig:
        return SavedModelConfig(
            config_id=row.config_id,
            route=row.route,  # type: ignore[arg-type]
            display_name=row.display_name,
            provider_kind=row.provider_kind,  # type: ignore[arg-type]
            base_url=row.base_url,
            model_name=row.model_name,
            api_key_masked=row.api_key_masked,
            last_tested_at=row.last_tested_at,
            last_test_signature=row.last_test_signature,
            last_test_result=row.last_test_result or {},
            legacy_imported=bool(row.legacy_imported),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_model_route_selection(row: ModelRouteSelectionRecord) -> ModelRouteSelection:
        return ModelRouteSelection(
            route=row.route,  # type: ignore[arg-type]
            active_source=row.active_source if row.active_source in {"system_default", "custom"} else "system_default",  # type: ignore[arg-type]
            active_config_id=row.active_config_id,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _load_profiles(
        payload_profiles: dict[str, Any],
        encrypted_keys: dict[str, str],
        legacy_custom: dict[str, Any],
    ) -> dict[str, ModelProviderProfile]:
        profiles: dict[str, ModelProviderProfile] = {}
        for route in ("chat", "embedding", "rerank"):
            raw = payload_profiles.get(route) or {}
            raw_custom = raw.get("custom_model") or (legacy_custom if route == "chat" else {})
            custom = CustomModelConfig(
                provider_kind=raw_custom.get("provider_kind", "openai_compatible"),
                base_url=raw_custom.get("base_url"),
                model_name=raw_custom.get("model_name", ""),
                has_api_key=bool(encrypted_keys.get(route)),
                api_key_masked=raw_custom.get("api_key_masked"),
            )
            profiles[route] = ModelProviderProfile(
                route=route,  # type: ignore[arg-type]
                model_preset="custom" if raw.get("model_preset") == "custom" else "system_default",
                custom_model=custom,
            )
        return profiles

    @staticmethod
    def _defaults() -> dict[str, Any]:
        model_profiles = {
            route: ModelProviderProfile(route=route, custom_model=CustomModelConfig())  # type: ignore[arg-type]
            for route in ("chat", "embedding", "rerank")
        }
        return {
            "language": "zh",
            "theme": "dark",
            "notification_mode": "important",
            "model_preset": "system_default",
            "custom_model": CustomModelConfig().model_dump(),
            "model_profiles": model_profiles,
        }
