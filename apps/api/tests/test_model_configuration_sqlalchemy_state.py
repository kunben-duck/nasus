from __future__ import annotations

from typing import Any

from apps.api.app.application.platform.model_settings import (
    CustomModelConfig,
    ModelProviderProfile,
)
from apps.api.app.infrastructure.llm import LLMGateway
from apps.api.app.infrastructure.platform.model_configuration_state import (
    SQLAlchemyModelConfigurationState,
)


class MutableSettingsRepository:
    def __init__(self) -> None:
        self.payload: dict[str, Any] = {
            "language": "en",
            "theme": "dark",
            "notification_mode": "important",
            "model_preset": "system_default",
            "custom_model": CustomModelConfig().model_dump(),
            "model_profiles": {
                route: ModelProviderProfile(route=route)
                for route in ("chat", "embedding", "rerank")
            },
        }
        self.keys: dict[str, str] = {"chat": "encrypted-chat-key"}
        self.loads = 0

    def load(self) -> tuple[dict[str, Any], dict[str, str]]:
        self.loads += 1
        return self.payload, dict(self.keys)


def test_sqlalchemy_model_configuration_state_observes_external_commits() -> None:
    repository = MutableSettingsRepository()
    state = SQLAlchemyModelConfigurationState(repository, LLMGateway())

    first = state.get_settings()
    repository.payload = {**repository.payload, "language": "zh", "theme": "light"}
    repository.keys["embedding"] = "encrypted-embedding-key"
    second = state.get_settings()

    assert first.language == "en"
    assert first.theme == "dark"
    assert second.language == "zh"
    assert second.theme == "light"
    assert state.legacy_encrypted_api_keys() == repository.keys
    assert repository.loads == 3
