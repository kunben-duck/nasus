from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Protocol
from urllib.parse import urlsplit

from .model_configuration_ports import ModelConfigurationSecretPort
from .model_settings import SavedModelConfig


@dataclass(frozen=True)
class ModelExecutionBinding:
    config_id: str
    provider: str
    model_name: str
    base_url: str
    config_digest: str


@dataclass(frozen=True)
class ResolvedModelExecution:
    binding: ModelExecutionBinding
    api_key: str = field(repr=False, compare=False)


class ModelExecutionConfigurationPort(Protocol):
    def get_model_config_snapshot(self, config_id: str) -> tuple[SavedModelConfig, str]: ...


class ModelExecutionProfileApplicationService:
    """Pin one explicitly selected saved model, without reading the mutable active route twice."""

    def __init__(self, repository: ModelExecutionConfigurationPort, secrets: ModelConfigurationSecretPort):
        self.repository, self.secrets = repository, secrets

    def resolve(self, config_id: str, *, route: str = "chat") -> ResolvedModelExecution:
        config, encrypted = self.repository.get_model_config_snapshot(config_id)
        if route not in {"chat", "embedding"}:
            raise ValueError("unsupported pinned model route")
        if (config.route != route or config.legacy_imported or config.last_test_result.get("ok") is not True
                or not config.last_tested_at or not config.last_test_signature):
            raise ValueError(f"analysis requires a saved, successfully tested {route} model")
        defaults = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1",
                    "gemini": "https://generativelanguage.googleapis.com/v1beta", "openai_compatible": ""}
        if config.provider_kind not in defaults:
            raise ValueError("semantic analysis does not allow fallback providers")
        if route == "embedding" and config.provider_kind not in {"openai", "openai_compatible"}:
            raise ValueError("versioned indexing requires a native OpenAI-compatible embedding endpoint")
        if not config.model_name.strip() or len(config.model_name) > 256 or any(ord(c) < 32 for c in config.model_name):
            raise ValueError("saved model name is invalid")
        base = (config.base_url or defaults[config.provider_kind]).rstrip("/")
        url = urlsplit(base)
        if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment
                or any(ord(c) < 33 for c in base) or len(base) > 2048):
            raise ValueError("model egress requires an explicit HTTPS destination without URL credentials")
        key = self.secrets.decrypt_api_key(encrypted)
        if not key.strip():
            raise ValueError("saved model credential is unavailable")
        snapshot = {"config_id": config.config_id, "provider": config.provider_kind, "model_name": config.model_name,
                    "base_url": base, "updated_at": config.updated_at, "tested_at": config.last_tested_at,
                    "test_signature": config.last_test_signature,
                    "credential_digest": hashlib.sha256(key.encode()).hexdigest()}
        if route != "chat":
            snapshot["route"] = route
        digest = "sha256:" + hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return ResolvedModelExecution(ModelExecutionBinding(config.config_id, config.provider_kind, config.model_name, base, digest), key)
