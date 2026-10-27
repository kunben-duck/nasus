"""Native generation ACL: no framework tools, redirects, retries or fallback."""
import asyncio
import json
from urllib.parse import quote

import httpx

from ...application.quality_loop.generation_executor import NativeGenerationReply
from ...application.quality_loop.generation_execution_inputs import GENERATION_TIMEOUT_SECONDS


class TestDesignModelFailure(RuntimeError):
    __test__ = False


class HTTPTestDesignModel:
    __test__ = False
    MAX_WIRE_BYTES = 4 * 1024 * 1024

    def __init__(self, *, transport=None):
        self.transport = transport

    async def generate(self, system, content, model, *, max_output_tokens):
        try:
            return await asyncio.wait_for(self._request(system, content, model, max_output_tokens), GENERATION_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise TestDesignModelFailure("native test-design provider failed or returned an incomplete response; do not resend") from None

    async def _request(self, system, content, model, max_output_tokens):
        binding = model.binding
        headers = {"Content-Type": "application/json"}
        if binding.provider in {"openai", "openai_compatible"}:
            url = binding.base_url + "/chat/completions"
            headers["Authorization"] = "Bearer " + model.api_key
            body = {"model": binding.model_name, "stream": False, "max_tokens": max_output_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        elif binding.provider == "anthropic":
            url = binding.base_url + "/messages"
            headers.update({"x-api-key": model.api_key, "anthropic-version": "2023-06-01"})
            body = {"model": binding.model_name, "max_tokens": max_output_tokens, "system": system,
                "messages": [{"role": "user", "content": content}]}
        elif binding.provider == "gemini":
            url = binding.base_url + "/models/" + quote(binding.model_name, safe="") + ":generateContent"
            headers["x-goog-api-key"] = model.api_key
            body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": content}]}],
                "generationConfig": {"maxOutputTokens": max_output_tokens, "responseMimeType": "application/json"}}
        else:
            raise TestDesignModelFailure("unsupported native provider")
        wire = json.dumps(body, ensure_ascii=False).encode()
        if len(wire) > self.MAX_WIRE_BYTES:
            raise TestDesignModelFailure("complete generation input exceeds the transport limit; no source was dropped")
        async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False,
                                     transport=self.transport) as client:
            async with client.stream("POST", url, headers=headers, content=wire) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise TestDesignModelFailure("generation requires a complete success response")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.MAX_WIRE_BYTES:
                        raise TestDesignModelFailure("native generation response exceeds transport limit")
                    chunks.append(chunk)

        def distinct(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise TestDesignModelFailure("ambiguous native response")
                value[key] = item
            return value

        payload = json.loads(b"".join(chunks), object_pairs_hook=distinct)
        usage = payload.get("usage", {})
        if binding.provider in {"openai", "openai_compatible"}:
            choices = payload["choices"]
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop" or choices[0]["message"].get("tool_calls") or choices[0]["message"].get("function_call"):
                raise TestDesignModelFailure("incomplete native generation response")
            result = choices[0]["message"]["content"]
            counts = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
        elif binding.provider == "anthropic":
            if payload.get("stop_reason") != "end_turn" or any(item.get("type") != "text" for item in payload["content"]):
                raise TestDesignModelFailure("incomplete native generation response")
            result = "".join(item["text"] for item in payload["content"])
            inputs = [usage.get("input_tokens"), usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0)]
            if any(type(item) is not int or item < 0 for item in inputs):
                raise TestDesignModelFailure("native input usage is unavailable")
            counts = (sum(inputs), usage.get("output_tokens"))
        else:
            candidates = payload["candidates"]
            if len(candidates) != 1 or candidates[0].get("finishReason") != "STOP" or payload.get("promptFeedback", {}).get("blockReason"):
                raise TestDesignModelFailure("incomplete native generation response")
            parts = candidates[0]["content"]["parts"]
            if any(set(item) != {"text"} for item in parts):
                raise TestDesignModelFailure("unexpected native generation tool/thought part")
            result = "".join(item["text"] for item in parts)
            usage = payload.get("usageMetadata", {})
            outputs = [usage.get("candidatesTokenCount"), usage.get("thoughtsTokenCount", 0)]
            if any(type(item) is not int or item < 0 for item in outputs):
                raise TestDesignModelFailure("native output usage is unavailable")
            counts = (usage.get("promptTokenCount"), sum(outputs))
        if type(result) is not str or not result.strip() or len(result.encode()) > 1024 * 1024:
            raise TestDesignModelFailure("empty or oversized native generation content")
        if any(type(count) is not int or count <= 0 for count in counts):
            raise TestDesignModelFailure("native usage is missing; do not estimate or retry")
        return NativeGenerationReply(result, *counts, "provider")
