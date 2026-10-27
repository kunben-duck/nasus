from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import apps.api.app.infrastructure.llm.gateway as gateway_module
from apps.api.app.application.agent.reply_ports import AgentReplyGenerationEvent
from apps.api.app.application.platform.model_settings import ProviderStatus, StudioSettings
from apps.api.app.infrastructure.llm.gateway import LLMGateway


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            await asyncio.sleep(0)
            yield line


def _install_stream(monkeypatch, lines: list[str]) -> None:
    class _FakeAsyncClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return _FakeStreamResponse(lines)

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", _FakeAsyncClient)


async def _collect(events: AsyncIterator[AgentReplyGenerationEvent]):
    return [event async for event in events]


def test_openai_compatible_stream_parses_unicode_deltas_and_usage(monkeypatch) -> None:
    _install_stream(monkeypatch, [
        f"data: {json.dumps({'choices': [{'delta': {'content': '你好'}}]}, ensure_ascii=False)}",
        f"data: {json.dumps({'choices': [{'delta': {'content': ' Nasus'}}]})}",
        f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 7, 'completion_tokens': 3}})}",
        "data: [DONE]",
    ])

    events = asyncio.run(_collect(LLMGateway()._stream_openai_compatible(
        base_url="https://provider.example/v1",
        api_key="secret",
        model_name="chat-model",
        provider="openai_compatible",
        system_prompt="system",
        user_message="user",
        context_snapshot="context",
        history_snapshot="history",
    )))

    assert "".join(event.delta for event in events if event.kind == "delta") == "你好 Nasus"
    usage = next(event for event in events if event.kind == "usage")
    assert (usage.input_tokens, usage.output_tokens, usage.usage_source) == (7, 3, "provider")


def test_gemini_stream_parses_deltas_and_usage(monkeypatch) -> None:
    _install_stream(monkeypatch, [
        f"data: {json.dumps({'candidates': [{'content': {'parts': [{'text': 'Gem'}, {'text': 'ini'}]}}]})}",
        f"data: {json.dumps({'usageMetadata': {'promptTokenCount': 5, 'candidatesTokenCount': 2}})}",
    ])

    events = asyncio.run(_collect(LLMGateway()._stream_gemini(
        model_name="gemini-model",
        api_key="secret",
        system_prompt="system",
        user_message="user",
        context_snapshot="context",
        history_snapshot="history",
    )))

    assert [event.delta for event in events if event.kind == "delta"] == ["Gem", "ini"]
    usage = next(event for event in events if event.kind == "usage")
    assert (usage.input_tokens, usage.output_tokens) == (5, 2)


def test_anthropic_stream_parses_deltas_and_usage(monkeypatch) -> None:
    _install_stream(monkeypatch, [
        f"data: {json.dumps({'type': 'message_start', 'message': {'usage': {'input_tokens': 9}}})}",
        f"data: {json.dumps({'type': 'content_block_delta', 'delta': {'text': 'Claude'}})}",
        f"data: {json.dumps({'type': 'message_delta', 'usage': {'output_tokens': 4}})}",
    ])

    events = asyncio.run(_collect(LLMGateway()._stream_anthropic(
        model_name="claude-model",
        api_key="secret",
        system_prompt="system",
        user_message="user",
        context_snapshot="context",
        history_snapshot="history",
    )))

    assert [event.delta for event in events if event.kind == "delta"] == ["Claude"]
    usage = next(event for event in events if event.kind == "usage")
    assert (usage.input_tokens, usage.output_tokens) == (9, 4)


class _ControlledGateway(LLMGateway):
    def __init__(self, events: list[AgentReplyGenerationEvent]) -> None:
        super().__init__()
        self._events = events

    async def _stream_provider(self, **_kwargs):
        for event in self._events:
            yield event
        raise RuntimeError("provider disconnected")


def _live_settings() -> StudioSettings:
    return StudioSettings(
        model_provider="openai",
        model_name="live-model",
        runtime_mode="live",
        active_provider_status=ProviderStatus(
            provider="openai",
            available=True,
            configured_via="system_default",
            mode="live",
            reason="configured",
        ),
    )


def _stream_gateway(gateway: LLMGateway):
    return gateway.stream_reply(
        settings=_live_settings(),
        system_prompt="system",
        user_message="user",
        context_snapshot="context",
        history_snapshot="history",
        fallback_text="fallback answer",
    )


def test_stream_falls_back_only_before_first_provider_delta() -> None:
    events = asyncio.run(_collect(_stream_gateway(_ControlledGateway([]))))

    assert [event.kind for event in events] == ["started", "delta", "usage", "completed"]
    assert [event.delta for event in events if event.kind == "delta"] == ["fallback answer"]


def test_stream_preserves_partial_output_and_does_not_append_fallback() -> None:
    provider_delta = AgentReplyGenerationEvent(
        kind="delta",
        provider="openai",
        model_name="live-model",
        mode="live",
        reason="provider_success",
        delta="partial",
    )
    events = asyncio.run(_collect(_stream_gateway(_ControlledGateway([provider_delta]))))

    assert [event.kind for event in events] == ["started", "delta", "failed"]
    assert "".join(event.delta for event in events) == "partial"
    assert events[-1].content == "partial"
    assert "fallback answer" not in "".join(event.delta for event in events)
