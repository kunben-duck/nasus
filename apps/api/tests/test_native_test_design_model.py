import asyncio
import json

import httpx
import pytest

from apps.api.app.application.quality_loop.generation_execution_inputs import generation_messages
from apps.api.app.domain.quality_loop.test_design_generation import compile_generation_input
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel, TestDesignModelFailure
from apps.api.tests.test_semantic_link_model import native_reply, resolved, saved_config
from apps.api.tests.test_test_design_generation import generation_inputs, case_output


@pytest.mark.parametrize("provider", ["openai", "openai_compatible", "anthropic", "gemini"])
def test_native_generation_transmits_complete_input_and_preserves_unicode(provider):
    prepared = compile_generation_input(*generation_inputs())
    content = json.dumps(case_output(prepared), ensure_ascii=False).replace("Synthetic proposal", "明确的中文草稿")
    calls = []
    def handle(request):
        calls.append(request)
        body = json.loads(request.content)
        text = body["contents"][0]["parts"][0]["text"] if provider == "gemini" else body["messages"][-1]["content"]
        assert json.loads(text) == prepared
        assert (body["generationConfig"]["maxOutputTokens"] if provider == "gemini" else body["max_tokens"]) == 8192
        return httpx.Response(200, json=native_reply(provider, content))
    reply = asyncio.run(HTTPTestDesignModel(transport=httpx.MockTransport(handle)).generate(
        *generation_messages(prepared), resolved(saved_config(provider_kind=provider)), max_output_tokens=8192))
    assert reply.content == content and reply.usage_source == "provider" and len(calls) == 1


@pytest.mark.parametrize("provider", ["openai", "openai_compatible", "anthropic", "gemini"])
@pytest.mark.parametrize("failure", ["redirect", "server", "usage", "truncated", "tool", "duplicate_json", "disconnect"])
def test_incomplete_provider_response_never_retries_redirects_or_falls_back(provider, failure):
    calls = []
    def handle(request):
        calls.append(request)
        if failure == "disconnect":
            raise httpx.ReadError("private-provider-key source-body", request=request)
        if failure == "redirect":
            return httpx.Response(307, headers={"location": "https://other.example"})
        if failure == "server":
            return httpx.Response(500, text="private-provider-key source-body")
        if failure == "duplicate_json":
            return httpx.Response(200, text='{"choices":[],"choices":[]}')
        payload = native_reply(provider, "response-data")
        if failure == "usage":
            payload.pop("usage" if provider != "gemini" else "usageMetadata")
        elif provider in {"openai", "openai_compatible"}:
            if failure == "truncated":
                payload["choices"][0]["finish_reason"] = "length"
            else:
                payload["choices"][0]["message"]["tool_calls"] = [{}]
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
    with pytest.raises(TestDesignModelFailure) as caught:
        asyncio.run(HTTPTestDesignModel(transport=httpx.MockTransport(handle)).generate("system", "untrusted source", resolved(saved_config(provider_kind=provider)), max_output_tokens=8192))
    assert len(calls) == 1 and "private-provider-key" not in str(caught.value) and "source-body" not in str(caught.value)
