from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path
from typing import Any

from .models import CustomModelConfig, StudioSettings


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _state_dir() -> Path:
    return Path(os.getenv("NASUS_STATE_DIR", _repo_root() / ".nasus" / "state"))


class SettingsPersistence:
    def __init__(self) -> None:
        self.state_dir = _state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.state_dir / "settings.json"
        self.key_file = self.state_dir / "settings.key"
        self.secret = self._load_or_create_secret()

    def load(self) -> tuple[dict[str, Any], str]:
        if not self.settings_file.exists():
            return self._defaults(), ""

        payload = json.loads(self.settings_file.read_text(encoding="utf-8"))
        defaults = self._defaults()
        custom = payload.get("custom_model") or {}
        encrypted_secret = payload.get("custom_api_key_encrypted") or ""

        custom_model = {
            "provider_kind": custom.get("provider_kind", defaults["custom_model"]["provider_kind"]),
            "base_url": custom.get("base_url"),
            "model_name": custom.get("model_name", ""),
            "has_api_key": bool(encrypted_secret),
            "api_key_masked": custom.get("api_key_masked"),
        }

        loaded = {
            "language": payload.get("language", defaults["language"]),
            "theme": payload.get("theme", defaults["theme"]),
            "notification_mode": payload.get("notification_mode", defaults["notification_mode"]),
            "model_preset": self._normalize_model_preset(payload.get("model_preset", defaults["model_preset"])),
            "custom_model": custom_model,
        }
        return loaded, encrypted_secret

    def save(self, settings: StudioSettings, encrypted_custom_api_key: str) -> None:
        payload = {
            "version": 2,
            "language": settings.language,
            "theme": settings.theme,
            "notification_mode": settings.notification_mode,
            "model_preset": settings.model_preset,
            "custom_model": {
                "provider_kind": settings.custom_model.provider_kind,
                "base_url": settings.custom_model.base_url,
                "model_name": settings.custom_model.model_name,
                "api_key_masked": settings.custom_model.api_key_masked,
            },
            "custom_api_key_encrypted": encrypted_custom_api_key or None,
            "encryption_scheme": "openssl-aes-256-cbc-pbkdf2",
        }
        self.settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def encrypt_api_key(self, api_key: str) -> str:
        if not api_key:
            return ""
        return self._run_openssl(api_key, decrypt=False)

    def decrypt_api_key(self, encrypted_value: str) -> str:
        if not encrypted_value:
            return ""
        return self._run_openssl(encrypted_value, decrypt=True)

    @staticmethod
    def mask_api_key(api_key: str) -> str | None:
        if not api_key:
            return None
        return f"••••{api_key[-4:]}"

    def _run_openssl(self, value: str, *, decrypt: bool) -> str:
        command = [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-a",
            "-A",
            "-pass",
            "env:NASUS_SETTINGS_SECRET_VALUE",
        ]
        if decrypt:
            command.insert(2, "-d")

        env = os.environ.copy()
        env["NASUS_SETTINGS_SECRET_VALUE"] = self.secret
        try:
            result = subprocess.run(
                command,
                input=value.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                env=env,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            message = getattr(exc, "stderr", b"").decode("utf-8").strip() or str(exc)
            raise RuntimeError(f"settings encryption failed: {message}") from exc
        return result.stdout.decode("utf-8").strip()

    def _load_or_create_secret(self) -> str:
        env_secret = os.getenv("NASUS_SETTINGS_ENCRYPTION_SECRET")
        if env_secret:
            return env_secret
        if self.key_file.exists():
            return self.key_file.read_text(encoding="utf-8").strip()
        secret = secrets.token_urlsafe(48)
        self.key_file.write_text(secret, encoding="utf-8")
        try:
            os.chmod(self.key_file, 0o600)
        except OSError:
            pass
        return secret

    @staticmethod
    def _normalize_model_preset(value: str) -> str:
        if value == "custom":
            return "custom"
        return "system_default"

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "language": "zh",
            "theme": "dark",
            "notification_mode": "important",
            "model_preset": "system_default",
            "custom_model": CustomModelConfig().model_dump(),
        }
