import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.app.application.platform.model_execution_profiles import ModelExecutionProfileApplicationService
from apps.api.app.application.platform.model_settings import SavedModelConfig
from apps.api.app.application.system_image.semantic_link_output import validate_semantic_output
from apps.api.app.infrastructure.llm.semantic_link_model import HTTPSemanticLinkModel, SemanticModelFailure
from apps.api.tests.test_semantic_links import prepared_input, response


def saved_config(**changes):
    values = dict(config_id="model", route="chat", display_name="Test model", provider_kind="openai_compatible",
        base_url="https://models.example/v1", model_name="test-model", last_tested_at="2026-09-17T00:00:00+00:00",
        last_test_signature="tested-signature", last_test_result={"ok": True},
        created_at="2026-09-17T00:00:00+00:00", updated_at="2026-09-17T00:00:00+00:00")
    return SavedModelConfig(**{**values, **changes})


def resolved(config=None, key="private-provider-key"):
    repository = SimpleNamespace(get_model_config_snapshot=lambda ident: (config or saved_config(), "encrypted"))
    secrets = SimpleNamespace(decrypt_api_key=lambda encrypted: key)
    return ModelExecutionProfileApplicationService(repository, secrets).resolve("model")


def native_reply(provider, content):
    if provider in {"openai", "openai_compatible"}:
        return {"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45}}
    if provider == "anthropic":
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": content}],
                "usage": {"input_tokens": 123, "output_tokens": 45}}
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}],
            "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 45}}


def test_model_uses_one_atomic_snapshot_and_pins_secret_without_printing_it():
    calls = []
    def snapshot(ident):
        calls.append(ident)
        return saved_config(), "encrypted-secret"
    service = ModelExecutionProfileApplicationService(SimpleNamespace(get_model_config_snapshot=snapshot),
        SimpleNamespace(decrypt_api_key=lambda value: "private-provider-key"))
    model = service.resolve("model")
    assert calls == ["model"] and model.api_key == "private-provider-key"
    assert "private-provider-key" not in repr(model)
    assert model.binding == resolved().binding
    assert model.binding != resolved(key="rotated").binding
    assert model.binding != resolved(saved_config(model_name="other")).binding
    assert model.binding != resolved(saved_config(updated_at="later")).binding


@pytest.mark.parametrize("changes", [
    {"route": "embedding"}, {"legacy_imported": True}, {"last_test_result": {"ok": False}},
    {"last_test_result": {"ok": 1}}, {"last_tested_at": ""}, {"last_test_signature": ""},
    {"base_url": "http://models.example"}, {"base_url": "https://user:secret@models.example"},
    {"base_url": "https://models.example?key=secret"}, {"base_url": "https://models.example/#fragment"},
    {"base_url": "https://models.example/\n"}, {"base_url": ""}, {"model_name": "  "},
    {"model_name": "bad\nname"}, {"model_name": "x" * 257},
])
def test_unverified_or_unsafe_profile_cannot_be_resolved(changes):
    with pytest.raises(ValueError):
        resolved(saved_config(**changes))


@pytest.mark.parametrize("provider,path,header", [
    ("openai", "/v1/chat/completions", "Authorization"),
    ("openai_compatible", "/v1/chat/completions", "Authorization"),
    ("anthropic", "/v1/messages", "x-api-key"),
    ("gemini", "/v1/models/test-model:generateContent", "x-goog-api-key"),
])
def test_native_provider_request_is_pinned_and_unicode_response_is_validated(provider, path, header):
    prepared = prepared_input()
    content = json.dumps(response(prepared), ensure_ascii=False)
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.host == "models.example" and request.url.path == path
        assert request.url.query == b"" and "private-provider-key" in request.headers[header]
        body = json.loads(request.content)
        assert prepared.digest in request.content.decode() and "JSON Schema" in request.content.decode()
        if provider != "gemini":
            assert body["model"] == "test-model" and body["max_tokens"] == 8192
        return httpx.Response(200, json=native_reply(provider, content))
    result = asyncio.run(HTTPSemanticLinkModel(transport=httpx.MockTransport(handle)).generate(
        prepared, resolved(saved_config(provider_kind=provider))))
    assert result.content == content and len(calls) == 1
    assert (result.input_tokens, result.output_tokens, result.usage_source) == (123, 45, "provider")
    assert validate_semantic_output(prepared, result.content).status == "proposed"


@pytest.mark.parametrize("provider", ["openai", "openai_compatible", "anthropic", "gemini"])
@pytest.mark.parametrize("failure", ["truncated", "tool_call", "oversized", "server_error", "redirect", "invalid_json", "disconnect"])
def test_provider_failure_never_redirects_retries_falls_back_or_leaks_body(provider, failure):
    calls = []
    def handle(request):
        calls.append(request)
        if failure == "disconnect":
            raise httpx.ReadError("secret-body private-provider-key", request=request)
        if failure == "redirect":
            return httpx.Response(307, headers={"location": "https://other.example"})
        if failure == "server_error":
            return httpx.Response(500, text="secret-body private-provider-key")
        if failure == "invalid_json":
            return httpx.Response(200, text="secret-body not JSON")
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * (512 * 1024 + 1))
        payload = native_reply(provider, "secret-body")
        if provider in {"openai", "openai_compatible"}:
            if failure == "truncated":
                payload["choices"][0]["finish_reason"] = "length"
            else:
                payload["choices"][0]["message"]["tool_calls"] = [{"id": "unexpected"}]
        elif provider == "anthropic":
            if failure == "truncated":
                payload["stop_reason"] = "max_tokens"
            else:
                payload["content"].append({"type": "tool_use"})
        elif failure == "truncated":
            payload["candidates"][0]["finishReason"] = "MAX_TOKENS"
        else:
            payload["candidates"][0]["content"]["parts"].append({"functionCall": {}})
        return httpx.Response(200, json=payload)
    with pytest.raises(SemanticModelFailure) as error:
        asyncio.run(HTTPSemanticLinkModel(transport=httpx.MockTransport(handle)).generate(
            prepared_input(), resolved(saved_config(provider_kind=provider))))
    assert len(calls) == 1
    assert "secret-body" not in str(error.value) and "private-provider-key" not in str(error.value)


def test_timeout_is_bounded_and_cancellation_is_not_swallowed(monkeypatch):
    from apps.api.app.infrastructure.llm import semantic_link_model
    monkeypatch.setattr(semantic_link_model, "SEMANTIC_TIMEOUT_SECONDS", 0.01)
    async def slow(request):
        await asyncio.sleep(10)
    model = HTTPSemanticLinkModel(transport=httpx.MockTransport(slow))
    with pytest.raises(SemanticModelFailure):
        asyncio.run(model.generate(prepared_input(), resolved()))
    async def cancel():
        task = asyncio.create_task(model.generate(prepared_input(), resolved()))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())


def test_missing_usage_is_not_invented_and_request_budget_prevents_network():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
    model = HTTPSemanticLinkModel(transport=httpx.MockTransport(handle))
    result = asyncio.run(model.generate(prepared_input(), resolved()))
    assert (result.input_tokens, result.output_tokens, result.usage_source) == (0, 0, "none")
    with pytest.raises(SemanticModelFailure):
        asyncio.run(model.generate(SimpleNamespace(model_payload=lambda: {"huge": "x" * (512 * 1024)}), resolved()))
    assert len(calls) == 1
