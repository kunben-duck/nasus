from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import uuid4

import httpx

from ...application.platform.model_settings import (
    CustomModelConfig,
    ModelProviderProfile,
    ModelRoute,
    ModelRouteConfigurations,
    ProviderStatus,
    StudioSettings,
    StudioSettingsConnectionTestResponse,
)
from ...application.platform.llm_calls import LLMCallAuditPort
from ...domain.platform.llm_call import LLMCall, LLMCallContext


ProviderName = Literal["mock", "openai", "gemini", "anthropic", "openai_compatible"]
ModelPreset = Literal["system_default", "custom"]


@dataclass
class LLMReply:
    content: str
    provider: ProviderName
    model_name: str
    mode: Literal["live", "fallback"]
    reason: str
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usage_source: Literal["provider", "estimated", "none"] = "none"
    llm_call_id: str | None = None


@dataclass
class ProviderGeneration:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    usage_source: Literal["provider", "estimated", "none"] = "none"


@dataclass
class EmbeddingBatchResult:
    vectors: list[list[float]]
    provider: ProviderName
    model_name: str
    mode: Literal["live", "fallback"]
    dimensions: int
    reason: str
    llm_call_id: str | None = None


@dataclass
class RerankBatchResult:
    ranked_indices: list[int]
    provider: ProviderName
    model_name: str
    mode: Literal["live", "fallback"]
    reason: str
    latency_ms: int
    llm_call_id: str | None = None


class LLMGateway:
    def __init__(self, llm_call_audit: LLMCallAuditPort | None = None) -> None:
        self._llm_call_audit = llm_call_audit

    def build_settings(
        self,
        *,
        language: str,
        theme: str,
        notification_mode: str,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig | None = None,
        model_profiles: dict[ModelRoute, ModelProviderProfile] | None = None,
        model_configurations: dict[ModelRoute, ModelRouteConfigurations] | None = None,
    ) -> StudioSettings:
        profiles = self.build_model_profiles(model_preset=model_preset, custom_model=custom_model, model_profiles=model_profiles)
        chat_profile = profiles["chat"]
        return StudioSettings(
            language=language,  # type: ignore[arg-type]
            theme=theme,  # type: ignore[arg-type]
            model_preset=chat_profile.model_preset,
            notification_mode=notification_mode,  # type: ignore[arg-type]
            model_provider=chat_profile.model_provider,
            model_name=chat_profile.model_name,
            runtime_mode=chat_profile.runtime_mode,
            fallback_provider=chat_profile.fallback_provider,
            provider_statuses=chat_profile.provider_statuses,
            active_provider_status=chat_profile.active_provider_status,
            custom_model=chat_profile.custom_model,
            model_profiles=profiles,
            model_configurations=model_configurations or {},
        )

    def build_model_profiles(
        self,
        *,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig | None = None,
        model_profiles: dict[ModelRoute, ModelProviderProfile] | None = None,
    ) -> dict[ModelRoute, ModelProviderProfile]:
        profiles: dict[ModelRoute, ModelProviderProfile] = {}
        for route in ("chat", "embedding", "rerank"):
            existing = (model_profiles or {}).get(route)  # type: ignore[arg-type]
            preset = existing.model_preset if existing else ("system_default" if route != "chat" else model_preset)
            custom = existing.custom_model.model_copy(deep=True) if existing else CustomModelConfig()
            if route == "chat" and custom_model is not None and existing is None:
                custom = custom_model
            provider, model_name = self.resolve_settings(route, preset, custom)
            statuses = self.provider_statuses(route, custom)
            active_status = self._active_status(preset, statuses)
            profiles[route] = ModelProviderProfile(
                route=route,  # type: ignore[arg-type]
                model_preset=preset,
                model_provider=provider,
                model_name=model_name,
                runtime_mode="live" if active_status.available else "fallback",
                fallback_provider="mock",
                provider_statuses=statuses,
                active_provider_status=active_status,
                custom_model=custom,
            )
        return profiles

    def resolve_settings(self, route: ModelRoute, model_preset: ModelPreset, custom_model: CustomModelConfig) -> tuple[ProviderName, str]:
        if model_preset == "custom":
            return custom_model.provider_kind, custom_model.model_name or "custom-model"
        provider = self._resolve_default_provider(route)
        model_name = self._resolve_default_model(route, provider)
        return provider, model_name

    def provider_statuses(self, route: ModelRoute = "chat", custom_model: CustomModelConfig | None = None) -> list[ProviderStatus]:
        custom = custom_model or CustomModelConfig()
        return [
            self._system_default_status(route),
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
        call_context: LLMCallContext | None = None,
    ) -> LLMReply:
        started = time.perf_counter()
        provider = settings.model_provider
        request_text = "\n".join(
            (system_prompt, user_message, context_snapshot, history_snapshot)
        )
        if settings.runtime_mode == "fallback":
            return self._audit_reply(
                LLMReply(
                content=fallback_text,
                provider=provider,
                model_name=settings.model_name,
                mode="fallback",
                reason=settings.active_provider_status.reason,
                ),
                settings=settings,
                context=call_context,
                started=started,
                request_text=request_text,
            )

        try:
            content = await self._call_provider(
                provider=provider,
                model_name=settings.model_name,
                model_preset=settings.model_preset,
                custom_model=settings.custom_model,
                custom_api_key=custom_api_key,
                system_prompt=system_prompt,
                user_message=user_message,
                context_snapshot=context_snapshot,
                history_snapshot=history_snapshot,
            )
        except Exception:
            return self._audit_reply(
                LLMReply(
                content=fallback_text,
                provider=provider,
                model_name=settings.model_name,
                mode="fallback",
                reason="provider_error",
                model_calls=1,
                ),
                settings=settings,
                context=call_context,
                started=started,
                request_text=request_text,
            )

        generation = self._normalize_generation(
            content,
            input_text=request_text,
        )
        return self._audit_reply(
            LLMReply(
                content=generation.content.strip() or fallback_text,
                provider=provider,
                model_name=settings.model_name,
                mode="live",
                reason="provider_success",
                model_calls=1,
                input_tokens=generation.input_tokens,
                output_tokens=generation.output_tokens,
                usage_source=generation.usage_source,
            ),
            settings=settings,
            context=call_context,
            started=started,
            request_text=request_text,
        )

    async def test_connection(
        self,
        *,
        settings: StudioSettings,
        route: ModelRoute = "chat",
        custom_api_key: str | None = None,
    ) -> StudioSettingsConnectionTestResponse:
        started = time.perf_counter()
        profile = settings.model_profiles.get(route) or settings.model_profiles.get("chat")
        provider = profile.model_provider if profile else settings.model_provider
        model_name = profile.model_name if profile else settings.model_name
        runtime_mode = profile.runtime_mode if profile else settings.runtime_mode
        fallback_provider = profile.fallback_provider if profile else settings.fallback_provider
        active_status = profile.active_provider_status if profile else settings.active_provider_status
        custom_model = profile.custom_model if profile else settings.custom_model

        if runtime_mode == "fallback":
            return StudioSettingsConnectionTestResponse(
                ok=False,
                model_route=route,
                provider=provider,
                model_name=model_name,
                runtime_mode="fallback",
                fallback_provider=fallback_provider,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message=active_status.reason,
            )

        if route == "embedding" and provider in {"openai", "openai_compatible"}:
            probe_texts = ["Nasus embedding connection test"]
            try:
                await self._probe_embedding_provider(
                    route=route,
                    provider=provider,
                    model_name=model_name,
                    model_preset=profile.model_preset if profile else settings.model_preset,
                    custom_model=custom_model,
                    custom_api_key=custom_api_key,
                )
            except Exception as exc:
                reason = self._safe_provider_error(exc)
                self._audit_embedding(
                    EmbeddingBatchResult([], provider, model_name, "fallback", 0, reason),
                    selected_provider=provider,
                    selected_model_name=model_name,
                    context=LLMCallContext(purpose="settings.embedding.connection_test"),
                    started=started,
                    texts=probe_texts,
                    model_calls=1,
                )
                return StudioSettingsConnectionTestResponse(
                    ok=False,
                    model_route=route,
                    provider=provider,
                    model_name=model_name,
                    runtime_mode="fallback",
                    fallback_provider=fallback_provider,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    message=f"Embedding connection failed: {reason}",
                )

            self._audit_embedding(
                EmbeddingBatchResult([], provider, model_name, "live", 0, "provider_success"),
                selected_provider=provider,
                selected_model_name=model_name,
                context=LLMCallContext(purpose="settings.embedding.connection_test"),
                started=started,
                texts=probe_texts,
                model_calls=1,
            )
            return StudioSettingsConnectionTestResponse(
                ok=True,
                model_route=route,
                provider=provider,
                model_name=model_name,
                runtime_mode="live",
                fallback_provider=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message="Embedding connection succeeded.",
            )

        if route == "rerank" and provider in {"openai", "openai_compatible"}:
            try:
                rerank_result = await self.rerank_candidates(
                    settings=settings,
                    query="Nasus rerank connection test",
                    documents=["system image", "quality loop"],
                    custom_api_key=custom_api_key,
                    call_context=LLMCallContext(
                        purpose="settings.rerank.connection_test"
                    ),
                )
            except Exception as exc:
                return StudioSettingsConnectionTestResponse(
                    ok=False,
                    model_route=route,
                    provider=provider,
                    model_name=model_name,
                    runtime_mode="fallback",
                    fallback_provider=fallback_provider,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    message=f"Rerank connection failed: {self._safe_provider_error(exc)}",
                )
            if rerank_result.mode == "fallback":
                return StudioSettingsConnectionTestResponse(
                    ok=False,
                    model_route=route,
                    provider=provider,
                    model_name=model_name,
                    runtime_mode="fallback",
                    fallback_provider=fallback_provider,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    message=f"Rerank connection failed: {rerank_result.reason}",
                )

            return StudioSettingsConnectionTestResponse(
                ok=True,
                model_route=route,
                provider=provider,
                model_name=model_name,
                runtime_mode="live",
                fallback_provider=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message="Rerank connection succeeded.",
            )

        if route != "chat":
            return StudioSettingsConnectionTestResponse(
                ok=True,
                model_route=route,
                provider=provider,
                model_name=model_name,
                runtime_mode="live",
                fallback_provider=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message=f"{route} provider configuration is live. Runtime adapter probe will execute during retrieval jobs.",
            )

        request_text = "\n".join(
            (
                "Reply with exactly READY.",
                "Connection test",
                "Settings panel connection test",
                "No prior conversation history.",
            )
        )
        try:
            provider_reply = await self._call_provider(
                provider=provider,
                model_name=model_name,
                model_preset=profile.model_preset if profile else settings.model_preset,
                custom_model=custom_model,
                custom_api_key=custom_api_key,
                system_prompt="Reply with exactly READY.",
                user_message="Connection test",
                context_snapshot="Settings panel connection test",
                history_snapshot="No prior conversation history.",
            )
        except Exception as exc:
            reason = self._safe_provider_error(exc)
            self._audit_reply(
                LLMReply(
                    content="",
                    provider=provider,
                    model_name=model_name,
                    mode="fallback",
                    reason=reason,
                    model_calls=1,
                ),
                settings=settings,
                context=LLMCallContext(purpose="settings.chat.connection_test"),
                started=started,
                request_text=request_text,
            )
            return StudioSettingsConnectionTestResponse(
                ok=False,
                model_route=route,
                provider=provider,
                model_name=model_name,
                runtime_mode="fallback",
                fallback_provider=fallback_provider,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message=f"Connection failed: {reason}",
            )

        generation = self._normalize_generation(provider_reply, input_text=request_text)
        self._audit_reply(
            LLMReply(
                content=generation.content,
                provider=provider,
                model_name=model_name,
                mode="live",
                reason="provider_success",
                model_calls=1,
                input_tokens=generation.input_tokens,
                output_tokens=generation.output_tokens,
                usage_source=generation.usage_source,
            ),
            settings=settings,
            context=LLMCallContext(purpose="settings.chat.connection_test"),
            started=started,
            request_text=request_text,
        )
        return StudioSettingsConnectionTestResponse(
            ok=True,
            model_route=route,
            provider=provider,
            model_name=model_name,
            runtime_mode="live",
            fallback_provider=settings.fallback_provider,
            latency_ms=int((time.perf_counter() - started) * 1000),
            message="Connection succeeded.",
        )

    async def _probe_embedding_provider(
        self,
        *,
        route: ModelRoute,
        provider: ProviderName,
        model_name: str,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
    ) -> None:
        await self._call_embedding_provider(
            route=route,
            provider=provider,
            model_name=model_name,
            model_preset=model_preset,
            custom_model=custom_model,
            custom_api_key=custom_api_key,
            texts=["Nasus embedding connection test"],
        )

    async def embed_texts(
        self,
        *,
        settings: StudioSettings,
        texts: list[str],
        custom_api_key: str | None = None,
        call_context: LLMCallContext | None = None,
    ) -> EmbeddingBatchResult:
        started = time.perf_counter()
        profile = settings.model_profiles.get("embedding")
        provider = profile.model_provider if profile else settings.model_provider
        model_name = profile.model_name if profile else settings.model_name
        runtime_mode = profile.runtime_mode if profile else settings.runtime_mode
        custom_model = profile.custom_model if profile else settings.custom_model
        model_preset = profile.model_preset if profile else settings.model_preset
        safe_texts = [text if text.strip() else " " for text in texts]

        if not safe_texts:
            return self._audit_embedding(
                EmbeddingBatchResult([], provider, model_name, "fallback", 0, "no_input"),
                selected_provider=provider,
                selected_model_name=model_name,
                context=call_context,
                started=started,
                texts=safe_texts,
            )

        if runtime_mode == "live" and provider in {"openai", "openai_compatible"}:
            try:
                vectors = await self._call_embedding_provider(
                    route="embedding",
                    provider=provider,
                    model_name=model_name,
                    model_preset=model_preset,
                    custom_model=custom_model,
                    custom_api_key=custom_api_key,
                    texts=safe_texts,
                )
                dimensions = len(vectors[0]) if vectors else 0
                return self._audit_embedding(
                    EmbeddingBatchResult(vectors, provider, model_name, "live", dimensions, "provider_success"),
                    selected_provider=provider,
                    selected_model_name=model_name,
                    context=call_context,
                    started=started,
                    texts=safe_texts,
                    model_calls=1,
                )
            except Exception as exc:
                reason = self._safe_provider_error(exc)
                vectors = [self._fallback_vector(text) for text in safe_texts]
                return self._audit_embedding(
                    EmbeddingBatchResult(vectors, "mock", "mock-hash-embedding", "fallback", len(vectors[0]), reason),
                    selected_provider=provider,
                    selected_model_name=model_name,
                    context=call_context,
                    started=started,
                    texts=safe_texts,
                    model_calls=1,
                )

        vectors = [self._fallback_vector(text) for text in safe_texts]
        reason = "embedding provider is not live" if runtime_mode == "fallback" else f"unsupported embedding provider {provider}"
        return self._audit_embedding(
            EmbeddingBatchResult(vectors, "mock", "mock-hash-embedding", "fallback", len(vectors[0]), reason),
            selected_provider=provider,
            selected_model_name=model_name,
            context=call_context,
            started=started,
            texts=safe_texts,
        )

    async def rerank_candidates(
        self,
        *,
        settings: StudioSettings,
        query: str,
        documents: list[str],
        custom_api_key: str | None = None,
        call_context: LLMCallContext | None = None,
    ) -> RerankBatchResult:
        started = time.perf_counter()
        profile = settings.model_profiles.get("rerank")
        provider = profile.model_provider if profile else settings.model_provider
        model_name = profile.model_name if profile else settings.model_name
        runtime_mode = profile.runtime_mode if profile else settings.runtime_mode
        custom_model = profile.custom_model if profile else settings.custom_model
        model_preset = profile.model_preset if profile else settings.model_preset
        fallback_indices = list(range(len(documents)))

        if not documents:
            return self._audit_rerank(
                RerankBatchResult([], provider, model_name, "fallback", "no_input", 0),
                selected_provider=provider,
                selected_model_name=model_name,
                context=call_context,
                started=started,
                query=query,
                documents=documents,
            )

        if runtime_mode == "live" and provider in {"openai", "openai_compatible"}:
            try:
                ranked_indices = await self._call_rerank_provider(
                    route="rerank",
                    provider=provider,
                    model_name=model_name,
                    model_preset=model_preset,
                    custom_model=custom_model,
                    custom_api_key=custom_api_key,
                    query=query,
                    documents=documents,
                )
                return self._audit_rerank(RerankBatchResult(
                    ranked_indices=ranked_indices,
                    provider=provider,
                    model_name=model_name,
                    mode="live",
                    reason="provider_success",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                ), selected_provider=provider, selected_model_name=model_name,
                    context=call_context, started=started, query=query,
                    documents=documents, model_calls=1)
            except Exception as exc:
                return self._audit_rerank(RerankBatchResult(
                    ranked_indices=fallback_indices,
                    provider="mock",
                    model_name="rule-based-fusion",
                    mode="fallback",
                    reason=self._safe_provider_error(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                ), selected_provider=provider, selected_model_name=model_name,
                    context=call_context, started=started, query=query,
                    documents=documents, model_calls=1)

        reason = "rerank provider is not live" if runtime_mode == "fallback" else f"unsupported rerank provider {provider}"
        return self._audit_rerank(RerankBatchResult(
            ranked_indices=fallback_indices,
            provider="mock",
            model_name="rule-based-fusion",
            mode="fallback",
            reason=reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ), selected_provider=provider, selected_model_name=model_name,
            context=call_context, started=started, query=query,
            documents=documents)

    def _audit_reply(
        self,
        result: LLMReply,
        *,
        settings: StudioSettings,
        context: LLMCallContext | None,
        started: float,
        request_text: str,
    ) -> LLMReply:
        call = self._new_llm_call(
            route="chat",
            context=context or LLMCallContext(purpose="unclassified.chat"),
            provider=result.provider,
            model_name=result.model_name,
            selected_provider=settings.model_provider,
            selected_model_name=settings.model_name,
            runtime_mode=result.mode,
            reason=result.reason,
            model_calls=result.model_calls,
            input_token_count=result.input_tokens,
            output_token_count=result.output_tokens,
            usage_source=result.usage_source,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_item_count=1,
            output_item_count=1 if result.content else 0,
            request_hash=self._content_hash(request_text),
            response_hash=self._content_hash(result.content),
        )
        self._persist_llm_call(call)
        result.llm_call_id = call.id
        return result

    def _audit_embedding(
        self,
        result: EmbeddingBatchResult,
        *,
        selected_provider: str,
        selected_model_name: str,
        context: LLMCallContext | None,
        started: float,
        texts: list[str],
        model_calls: int = 0,
    ) -> EmbeddingBatchResult:
        input_text = "\n".join(texts)
        call = self._new_llm_call(
            route="embedding",
            context=context or LLMCallContext(purpose="unclassified.embedding"),
            provider=result.provider,
            model_name=result.model_name,
            selected_provider=selected_provider,
            selected_model_name=selected_model_name,
            runtime_mode=result.mode,
            reason=result.reason,
            model_calls=model_calls,
            input_token_count=self._estimate_tokens(input_text),
            output_token_count=0,
            usage_source="estimated" if input_text else "none",
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_item_count=len(texts),
            output_item_count=len(result.vectors),
            request_hash=self._content_hash(input_text),
            response_hash=self._content_hash(
                f"{result.model_name}:{result.dimensions}:{len(result.vectors)}"
            ),
        )
        self._persist_llm_call(call)
        result.llm_call_id = call.id
        return result

    def _audit_rerank(
        self,
        result: RerankBatchResult,
        *,
        selected_provider: str,
        selected_model_name: str,
        context: LLMCallContext | None,
        started: float,
        query: str,
        documents: list[str],
        model_calls: int = 0,
    ) -> RerankBatchResult:
        input_text = "\n".join((query, *documents))
        call = self._new_llm_call(
            route="rerank",
            context=context or LLMCallContext(purpose="unclassified.rerank"),
            provider=result.provider,
            model_name=result.model_name,
            selected_provider=selected_provider,
            selected_model_name=selected_model_name,
            runtime_mode=result.mode,
            reason=result.reason,
            model_calls=model_calls,
            input_token_count=self._estimate_tokens(input_text),
            output_token_count=0,
            usage_source="estimated" if input_text else "none",
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_item_count=len(documents),
            output_item_count=len(result.ranked_indices),
            request_hash=self._content_hash(input_text),
            response_hash=self._content_hash(
                ",".join(str(index) for index in result.ranked_indices)
            ),
        )
        self._persist_llm_call(call)
        result.llm_call_id = call.id
        return result

    @staticmethod
    def _new_llm_call(
        *,
        route: Literal["chat", "embedding", "rerank"],
        context: LLMCallContext,
        provider: str,
        model_name: str,
        selected_provider: str,
        selected_model_name: str,
        runtime_mode: Literal["live", "fallback"],
        reason: str,
        model_calls: int,
        input_token_count: int,
        output_token_count: int,
        usage_source: Literal["provider", "estimated", "none"],
        latency_ms: int,
        input_item_count: int,
        output_item_count: int,
        request_hash: str,
        response_hash: str,
    ) -> LLMCall:
        outcome = "success" if runtime_mode == "live" else "fallback"
        if reason == "no_input":
            outcome = "skipped"
        return LLMCall(
            id=f"llmcall_{uuid4().hex[:20]}",
            occurred_at=datetime.now(timezone.utc),
            route=route,
            purpose=context.purpose,
            provider=provider,
            model_name=model_name,
            selected_provider=selected_provider,
            selected_model_name=selected_model_name,
            runtime_mode=runtime_mode,
            outcome=outcome,  # type: ignore[arg-type]
            reason=reason,
            prompt_id=context.prompt_id,
            prompt_version=context.prompt_version,
            project_id=context.project_id,
            version_id=context.version_id,
            task_id=context.task_id,
            conversation_id=context.conversation_id,
            agent_goal_id=context.agent_goal_id,
            tool_invocation_id=context.tool_invocation_id,
            model_calls=model_calls,
            input_token_count=input_token_count,
            output_token_count=output_token_count,
            usage_source=usage_source,
            latency_ms=latency_ms,
            input_item_count=input_item_count,
            output_item_count=output_item_count,
            request_hash=request_hash,
            response_hash=response_hash,
        )

    def _persist_llm_call(self, call: LLMCall) -> None:
        if self._llm_call_audit is not None:
            self._llm_call_audit.persist_llm_call(call)

    @staticmethod
    def _content_hash(content: str) -> str:
        return f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"

    async def _call_embedding_provider(
        self,
        *,
        route: ModelRoute,
        provider: ProviderName,
        model_name: str,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
        texts: list[str],
    ) -> list[list[float]]:
        base_url, api_key = self._provider_base_url_and_key(
            route=route,
            provider=provider,
            model_preset=model_preset,
            custom_model=custom_model,
            custom_api_key=custom_api_key,
        )
        payload = {"model": model_name, "input": texts}
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        vectors = [item.get("embedding") for item in body.get("data", [])]
        if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
            raise RuntimeError("provider returned invalid embedding payload")
        return [[float(value) for value in vector] for vector in vectors]

    async def _call_rerank_provider(
        self,
        *,
        route: ModelRoute,
        provider: ProviderName,
        model_name: str,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
        query: str,
        documents: list[str],
    ) -> list[int]:
        base_url, api_key = self._provider_base_url_and_key(
            route=route,
            provider=provider,
            model_preset=model_preset,
            custom_model=custom_model,
            custom_api_key=custom_api_key,
        )
        payload = {"model": model_name, "query": query, "documents": documents, "top_n": len(documents)}
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/rerank",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        results = body.get("results") or body.get("data")
        if not isinstance(results, list):
            raise RuntimeError("provider returned invalid rerank payload")

        ranked: list[tuple[int, float]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            raw_index = item.get("index", item.get("document_index"))
            if raw_index is None and isinstance(item.get("document"), dict):
                raw_index = item["document"].get("index")
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(documents):
                continue
            score = item.get("relevance_score", item.get("score", 0))
            try:
                ranked.append((index, float(score)))
            except (TypeError, ValueError):
                ranked.append((index, 0.0))
        if not ranked:
            raise RuntimeError("provider returned no usable rerank results")

        seen: set[int] = set()
        ordered: list[int] = []
        for index, _score in sorted(ranked, key=lambda pair: pair[1], reverse=True):
            if index not in seen:
                seen.add(index)
                ordered.append(index)
        ordered.extend(index for index in range(len(documents)) if index not in seen)
        return ordered

    def _provider_base_url_and_key(
        self,
        *,
        route: ModelRoute,
        provider: ProviderName,
        model_preset: ModelPreset,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
    ) -> tuple[str, str]:
        if model_preset == "custom":
            if provider == "openai":
                api_key = custom_api_key or ""
                if not api_key:
                    raise RuntimeError("missing custom api key")
                return "https://api.openai.com/v1", api_key
            if provider == "openai_compatible":
                base_url = (custom_model.base_url or "").rstrip("/")
                api_key = custom_api_key or ""
                if not base_url:
                    raise RuntimeError("missing custom base url")
                if not api_key:
                    raise RuntimeError("missing custom api key")
                return base_url, api_key
            raise RuntimeError(f"provider {provider} does not support route {route}")

        if provider == "openai":
            return "https://api.openai.com/v1", os.environ["OPENAI_API_KEY"]
        if provider == "openai_compatible":
            base_url = self._resolve_openai_compatible_base_url(route)
            api_key = self._resolve_openai_compatible_api_key(route)
            if not base_url:
                raise RuntimeError(f"missing system default {route} base url")
            if not api_key:
                raise RuntimeError(f"missing system default {route} api key")
            return base_url, api_key
        raise RuntimeError(f"provider {provider} does not support route {route}")

    @staticmethod
    def _fallback_vector(text: str, dimensions: int = 32) -> list[float]:
        digest = sha256(text.encode("utf-8")).digest()
        values = []
        for index in range(dimensions):
            byte = digest[index % len(digest)]
            values.append(round((byte / 127.5) - 1.0, 6))
        return values

    def _active_status(self, model_preset: ModelPreset, statuses: list[ProviderStatus]) -> ProviderStatus:
        configured_via = "custom" if model_preset == "custom" else "system_default"
        return next(
            status
            for status in statuses
            if status.configured_via == configured_via
        )

    def _system_default_status(self, route: ModelRoute) -> ProviderStatus:
        provider = self._resolve_default_provider(route)
        if provider == "mock":
            return ProviderStatus(
                provider="mock",
                available=False,
                configured_via="system_default",
                mode="fallback",
                fallback_provider="mock",
                reason="System default is configured to use the local fallback provider.",
            )

        if provider == "openai_compatible":
            base_url = self._resolve_openai_compatible_base_url(route)
            api_key = self._resolve_openai_compatible_api_key(route)
            model_name = self._resolve_default_model(route, provider)
            missing = []
            if not base_url:
                missing.append(self._openai_compatible_base_url_env(route))
            if not api_key:
                missing.append(self._openai_compatible_api_key_env(route))
            if not model_name:
                missing.append(self._openai_compatible_model_env(route))
            available = not missing
            return ProviderStatus(
                provider="openai_compatible",
                available=available,
                configured_via="system_default",
                mode="live" if available else "fallback",
                fallback_provider=None if available else "mock",
                reason=(
                    f"System default {route} OpenAI-compatible provider is configured."
                    if available
                    else f"Missing {', '.join(missing)}; system default {route} route will fall back to mock."
                ),
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
                f"System default {route} provider {provider} is configured."
                if available
                else f"Missing {env_name}; system default {route} route will fall back to mock."
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

    @staticmethod
    def _safe_provider_error(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"provider returned HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.TimeoutException):
            return "provider request timed out"
        if isinstance(exc, httpx.RequestError):
            return f"provider request failed: {type(exc).__name__}"

        message = str(exc) or type(exc).__name__
        redactions = [
            (r"sk-[A-Za-z0-9_-]+", "sk-***REDACTED***"),
            (r"(?i)(authorization:\s*bearer\s+)[^\s,;]+", r"\1***REDACTED***"),
            (r"(?i)([?&](?:key|api_key|token|access_token)=)[^&\s]+", r"\1***REDACTED***"),
            (r"(?i)(api[-_ ]?key[\"'=:\s]+)[^\"'\s,}]+", r"\1***REDACTED***"),
        ]
        for pattern, replacement in redactions:
            message = re.sub(pattern, replacement, message)
        return message[:240]

    def _resolve_default_provider(self, route: ModelRoute) -> ProviderName:
        env_by_route = {
            "chat": "NASUS_DEFAULT_PROVIDER",
            "embedding": "NASUS_EMBEDDING_PROVIDER",
            "rerank": "NASUS_RERANK_PROVIDER",
        }
        configured = os.getenv(env_by_route[route], "").strip().lower()
        if not configured and route != "chat":
            configured = os.getenv("NASUS_DEFAULT_PROVIDER", "").strip().lower()
        configured = configured.replace("-", "_")
        if configured in {"openai", "gemini", "anthropic", "mock", "openai_compatible"}:
            return configured  # type: ignore[return-value]
        return "openai"

    def _resolve_default_model(self, route: ModelRoute, provider: ProviderName) -> str:
        route_override = {
            "chat": "NASUS_DEFAULT_MODEL",
            "embedding": "NASUS_EMBEDDING_MODEL",
            "rerank": "NASUS_RERANK_MODEL",
        }[route]
        override = os.getenv(route_override)
        if override:
            return override
        if route == "embedding":
            return os.getenv("NASUS_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
        if route == "rerank":
            return os.getenv("NASUS_RERANK_MODEL", "nasus-rerank-system-default")
        if provider == "openai_compatible":
            return os.getenv("NASUS_OPENAI_COMPATIBLE_MODEL", "openai-compatible-chat")
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
        model_preset: ModelPreset,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str | ProviderGeneration:
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
        if provider == "openai_compatible" and model_preset != "custom":
            return await self._call_openai_compatible(
                base_url=self._resolve_openai_compatible_base_url("chat"),
                api_key=self._resolve_openai_compatible_api_key("chat"),
                model_name=model_name,
                system_prompt=system_prompt,
                user_message=user_message,
                context_snapshot=context_snapshot,
                history_snapshot=history_snapshot,
            )
        return await self._call_custom(
            custom_model=custom_model,
            custom_api_key=custom_api_key,
            system_prompt=system_prompt,
            user_message=user_message,
            context_snapshot=context_snapshot,
            history_snapshot=history_snapshot,
        )

    def _openai_compatible_base_url_env(self, route: ModelRoute) -> str:
        return {
            "chat": "NASUS_DEFAULT_BASE_URL",
            "embedding": "NASUS_EMBEDDING_BASE_URL",
            "rerank": "NASUS_RERANK_BASE_URL",
        }[route]

    def _openai_compatible_api_key_env(self, route: ModelRoute) -> str:
        return {
            "chat": "NASUS_DEFAULT_API_KEY",
            "embedding": "NASUS_EMBEDDING_API_KEY",
            "rerank": "NASUS_RERANK_API_KEY",
        }[route]

    def _openai_compatible_model_env(self, route: ModelRoute) -> str:
        return {
            "chat": "NASUS_DEFAULT_MODEL",
            "embedding": "NASUS_EMBEDDING_MODEL",
            "rerank": "NASUS_RERANK_MODEL",
        }[route]

    def _resolve_openai_compatible_base_url(self, route: ModelRoute) -> str:
        route_value = os.getenv(self._openai_compatible_base_url_env(route), "").strip()
        fallback = os.getenv("NASUS_OPENAI_COMPATIBLE_BASE_URL", "").strip()
        return (route_value or fallback).rstrip("/")

    def _resolve_openai_compatible_api_key(self, route: ModelRoute) -> str:
        return (
            os.getenv(self._openai_compatible_api_key_env(route), "").strip()
            or os.getenv("NASUS_OPENAI_COMPATIBLE_API_KEY", "").strip()
        )

    async def _call_openai(
        self,
        model_name: str,
        api_key: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> ProviderGeneration:
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
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        return self._provider_generation(
            content,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            input_text="\n".join(
                (system_prompt, user_message, context_snapshot, history_snapshot)
            ),
        )

    async def _call_gemini(
        self,
        model_name: str,
        api_key: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> ProviderGeneration:
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
        content = body["candidates"][0]["content"]["parts"][0]["text"]
        usage = body.get("usageMetadata") or {}
        return self._provider_generation(
            content,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            input_text="\n".join(
                (system_prompt, user_message, context_snapshot, history_snapshot)
            ),
        )

    async def _call_anthropic(
        self,
        model_name: str,
        api_key: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> ProviderGeneration:
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
        content = "".join(
            block["text"] for block in body["content"] if block.get("type") == "text"
        )
        usage = body.get("usage") or {}
        return self._provider_generation(
            content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            input_text="\n".join(
                (system_prompt, user_message, context_snapshot, history_snapshot)
            ),
        )

    async def _call_custom(
        self,
        *,
        custom_model: CustomModelConfig,
        custom_api_key: str | None,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> str | ProviderGeneration:
        if not custom_api_key:
            raise RuntimeError("missing custom api key")

        if custom_model.provider_kind == "openai_compatible":
            base_url = (custom_model.base_url or "").rstrip("/")
            if not base_url:
                raise RuntimeError("missing custom base url")
            return await self._call_openai_compatible(
                base_url=base_url,
                api_key=custom_api_key,
                model_name=custom_model.model_name,
                system_prompt=system_prompt,
                user_message=user_message,
                context_snapshot=context_snapshot,
                history_snapshot=history_snapshot,
            )

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

    async def _call_openai_compatible(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
    ) -> ProviderGeneration:
        if not base_url:
            raise RuntimeError("missing OpenAI-compatible base url")
        if not api_key:
            raise RuntimeError("missing OpenAI-compatible api key")
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
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        return self._provider_generation(
            content,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            input_text="\n".join(
                (system_prompt, user_message, context_snapshot, history_snapshot)
            ),
        )

    @classmethod
    def _provider_generation(
        cls,
        content: str,
        *,
        input_tokens: object,
        output_tokens: object,
        input_text: str,
    ) -> ProviderGeneration:
        parsed_input = cls._non_negative_int(input_tokens)
        parsed_output = cls._non_negative_int(output_tokens)
        if parsed_input is not None and parsed_output is not None:
            return ProviderGeneration(
                content=content,
                input_tokens=parsed_input,
                output_tokens=parsed_output,
                usage_source="provider",
            )
        return ProviderGeneration(
            content=content,
            input_tokens=cls._estimate_tokens(input_text),
            output_tokens=cls._estimate_tokens(content),
            usage_source="estimated",
        )

    @classmethod
    def _normalize_generation(
        cls,
        generation: str | ProviderGeneration,
        *,
        input_text: str,
    ) -> ProviderGeneration:
        if isinstance(generation, ProviderGeneration):
            return generation
        return ProviderGeneration(
            content=generation,
            input_tokens=cls._estimate_tokens(input_text),
            output_tokens=cls._estimate_tokens(generation),
            usage_source="estimated",
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4) if text else 0

    @staticmethod
    def _non_negative_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return max(0, parsed)
