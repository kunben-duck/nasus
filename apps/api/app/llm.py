from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from .models import (
    CustomModelConfig,
    ProviderStatus,
    StudioSettings,
    StudioSettingsConnectionTestResponse,
)


ProviderName = Literal["mock", "openai", "gemini", "anthropic", "openai_compatible"]
ModelPreset = Literal["system_default", "custom"]


@dataclass
class LLMReply:
    content: str
    provider: ProviderName
    model_name: str
    mode: Literal["live", "fallback"]
    reason: str


class LLMGateway:
    def build_settings(
        self,
        *,
        language: str,
        theme: str,
        notification_mode: str,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig | None = None,
    ) -> StudioSettings:
        custom = custom_model or CustomModelConfig()
        provider, model_name = self.resolve_settings(model_preset, custom)
        statuses = self.provider_statuses(custom)
        active_status = self._active_status(model_preset, statuses)
        runtime_mode: Literal["live", "fallback"] = "live" if active_status.available else "fallback"
        return StudioSettings(
            language=language,  # type: ignore[arg-type]
            theme=theme,  # type: ignore[arg-type]
            model_preset=model_preset,
            notification_mode=notification_mode,  # type: ignore[arg-type]
            model_provider=provider,
            model_name=model_name,
            runtime_mode=runtime_mode,
            fallback_provider="mock",
            provider_statuses=statuses,
            active_provider_status=active_status,
            custom_model=custom,
        )

    def resolve_settings(self, model_preset: ModelPreset, custom_model: CustomModelConfig) -> tuple[ProviderName, str]:
        if model_preset == "custom":
            return custom_model.provider_kind, custom_model.model_name or "custom-model"
        provider = self._resolve_default_provider()
        model_name = self._resolve_default_model(provider)
        return provider, model_name

    def provider_statuses(self, custom_model: CustomModelConfig | None = None) -> list[ProviderStatus]:
        custom = custom_model or CustomModelConfig()
        return [
            self._system_default_status(),
            self._custom_provider_status(custom),
            self._mock_status(),
        ]

    async def generate_reply(
        self,
        *,
        settings: StudioSettings,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
        fallback_text: str,
        custom_api_key: str | None = None,
    ) -> LLMReply:
        provider = settings.model_provider
        if settings.runtime_mode == "fallback":
            return LLMReply(
                content=fallback_text,
                provider=provider,
                model_name=settings.model_name,
                mode="fallback",
                reason=settings.active_provider_status.reason,
            )

        try:
            content = await self._call_provider(
                provider=provider,
                model_name=settings.model_name,
                custom_model=settings.custom_model,
                custom_api_key=custom_api_key,
                system_prompt=system_prompt,
                user_message=user_message,
                context_snapshot=context_snapshot,
                history_snapshot=history_snapshot,
            )
        except Exception:
            return LLMReply(
                content=fallback_text,
                provider=provider,
                model_name=settings.model_name,
                mode="fallback",
                reason="provider_error",
            )

        return LLMReply(
            content=content.strip() or fallback_text,
            provider=provider,
            model_name=settings.model_name,
            mode="live",
            reason="provider_success",
        )

    async def test_connection(
        self,
        *,
        settings: StudioSettings,
        custom_api_key: str | None = None,
    ) -> StudioSettingsConnectionTestResponse:
        started = time.perf_counter()
        provider = settings.model_provider
        model_name = settings.model_name

        if settings.runtime_mode == "fallback":
            return StudioSettingsConnectionTestResponse(
                ok=False,
                provider=provider,
                model_name=model_name,
                runtime_mode="fallback",
                fallback_provider=settings.fallback_provider,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message=settings.active_provider_status.reason,
            )

        try:
            await self._call_provider(
                provider=provider,
                model_name=model_name,
                custom_model=settings.custom_model,
                custom_api_key=custom_api_key,
                system_prompt="Reply with exactly READY.",
                user_message="Connection test",
                context_snapshot="Settings panel connection test",
                history_snapshot="No prior conversation history.",
            )
        except Exception as exc:
            return StudioSettingsConnectionTestResponse(
                ok=False,
                provider=provider,
                model_name=model_name,
                runtime_mode="fallback",
                fallback_provider=settings.fallback_provider,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message=f"Connection failed: {exc}",
            )

        return StudioSettingsConnectionTestResponse(
            ok=True,
            provider=provider,
            model_name=model_name,
            runtime_mode="live",
            fallback_provider=settings.fallback_provider,
            latency_ms=int((time.perf_counter() - started) * 1000),
            message="Connection succeeded.",
        )

    def _active_status(self, model_preset: ModelPreset, statuses: list[ProviderStatus]) -> ProviderStatus:
        configured_via = "custom" if model_preset == "custom" else "system_default"
        return next(
            status
            for status in statuses
            if status.configured_via == configured_via
        )

    def _system_default_status(self) -> ProviderStatus:
        provider = self._resolve_default_provider()
        if provider == "mock":
            return ProviderStatus(
                provider="mock",
                available=False,
                configured_via="system_default",
                mode="fallback",
                fallback_provider="mock",
                reason="System default is configured to use the local fallback provider.",
            )

        env_name = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }[provider]
        available = bool(os.getenv(env_name))
        return ProviderStatus(
            provider=provider,
            available=available,
            configured_via="system_default",
            mode="live" if available else "fallback",
            fallback_provider=None if available else "mock",
            reason=(
                f"System default provider {provider} is configured."
                if available
                else f"Missing {env_name}; system default will fall back to mock."
            ),
        )

    def _custom_provider_status(self, custom_model: CustomModelConfig) -> ProviderStatus:
        has_model = bool(custom_model.model_name.strip())
        has_key = custom_model.has_api_key
        has_base = True
        if custom_model.provider_kind == "openai_compatible":
            has_base = bool((custom_model.base_url or "").strip())
        available = has_model and has_key and has_base

        if available:
            reason = f"Custom provider {custom_model.provider_kind} is fully configured."
        elif custom_model.provider_kind == "openai_compatible":
            reason = "Custom provider requires base URL, model name, and API key."
        else:
            reason = f"Custom provider {custom_model.provider_kind} requires model name and API key."

        return ProviderStatus(
            provider=custom_model.provider_kind,
            available=available,
            configured_via="custom",
            mode="live" if available else "fallback",
            fallback_provider=None if available else "mock",
            reason=reason,
        )

    @staticmethod
    def _mock_status() -> ProviderStatus:
        return ProviderStatus(
            provider="mock",
            available=True,
            configured_via="builtin",
            mode="live",
            fallback_provider=None,
            reason="Local deterministic fallback is always available.",
        )

    def _resolve_default_provider(self) -> ProviderName:
        configured = os.getenv("NASUS_DEFAULT_PROVIDER", "").strip().lower()
        if configured in {"openai", "gemini", "anthropic", "mock"}:
            return configured  # type: ignore[return-value]
        return "openai"

    def _resolve_default_model(self, provider: ProviderName) -> str:
        override = os.getenv("NASUS_DEFAULT_MODEL")
        if override:
            return override
        if provider == "gemini":
            return os.getenv("NASUS_GEMINI_MODEL", "gemini-2.5-pro")
        if provider == "anthropic":
            return os.getenv("NASUS_ANTHROPIC_MODEL", "claude-sonnet-4")
        if provider == "mock":
            return "nasus-system-default"
        return os.getenv("NASUS_OPENAI_MODEL", "gpt-5.4")

    async def _call_provider(
        self,
        *,
        provider: ProviderName,
        model_name: str,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str:
        if provider == "openai":
            return await self._call_openai(
                model_name,
                os.environ["OPENAI_API_KEY"],
                system_prompt,
                user_message,
                context_snapshot,
                history_snapshot,
            )
        if provider == "gemini":
            return await self._call_gemini(
                model_name,
                os.environ["GEMINI_API_KEY"],
                system_prompt,
                user_message,
                context_snapshot,
                history_snapshot,
            )
        if provider == "anthropic":
            return await self._call_anthropic(
                model_name,
                os.environ["ANTHROPIC_API_KEY"],
                system_prompt,
                user_message,
                context_snapshot,
                history_snapshot,
            )
        return await self._call_custom(
            custom_model=custom_model,
            custom_api_key=custom_api_key,
            system_prompt=system_prompt,
            user_message=user_message,
            context_snapshot=context_snapshot,
            history_snapshot=history_snapshot,
        )

    async def _call_openai(
        self,
        model_name: str,
        api_key: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Conversation memory:\n{history_snapshot}\n\n"
                        f"Conversation input:\n{user_message}\n\n"
                        f"Workspace context:\n{context_snapshot}"
                    ),
                },
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]

    async def _call_gemini(
        self,
        model_name: str,
        api_key: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{
                        "text": (
                            f"Conversation memory:\n{history_snapshot}\n\n"
                            f"Conversation input:\n{user_message}\n\n"
                            f"Workspace context:\n{context_snapshot}"
                        )
                    }],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}",
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        return body["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_anthropic(
        self,
        model_name: str,
        api_key: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str:
        payload = {
            "model": model_name,
            "max_tokens": 1200,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Conversation memory:\n{history_snapshot}\n\n"
                        f"Conversation input:\n{user_message}\n\n"
                        f"Workspace context:\n{context_snapshot}"
                    ),
                }
            ],
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        return "".join(block["text"] for block in body["content"] if block.get("type") == "text")

    async def _call_custom(
        self,
        *,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str:
        if not custom_api_key:
            raise RuntimeError("missing custom api key")

        if custom_model.provider_kind == "openai_compatible":
            base_url = (custom_model.base_url or "").rstrip("/")
            if not base_url:
                raise RuntimeError("missing custom base url")
            payload = {
                "model": custom_model.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Conversation memory:\n{history_snapshot}\n\n"
                            f"Conversation input:\n{user_message}\n\n"
                            f"Workspace context:\n{context_snapshot}"
                        ),
                    },
                ],
                "temperature": 0.2,
            }
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {custom_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            body = response.json()
            return body["choices"][0]["message"]["content"]

        if custom_model.provider_kind == "openai":
            return await self._call_openai(
                custom_model.model_name,
                custom_api_key,
                system_prompt,
                user_message,
                context_snapshot,
                history_snapshot,
            )
        if custom_model.provider_kind == "gemini":
            return await self._call_gemini(
                custom_model.model_name,
                custom_api_key,
                system_prompt,
                user_message,
                context_snapshot,
                history_snapshot,
            )
        return await self._call_anthropic(
            custom_model.model_name,
            custom_api_key,
            system_prompt,
            user_message,
            context_snapshot,
            history_snapshot,
        )
