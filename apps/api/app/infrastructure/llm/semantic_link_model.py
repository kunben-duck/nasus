from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import httpx

from ...application.system_image.semantic_link_output import SEMANTIC_LINK_INSTRUCTIONS, SemanticModelOutput
from ...application.system_image.semantic_model_port import SemanticModelReply, SEMANTIC_MAX_OUTPUT_TOKENS, SEMANTIC_TIMEOUT_SECONDS


class SemanticModelFailure(RuntimeError):
    pass


class HTTPSemanticLinkModel:
    """Single native structured generation; never repair, retry, redirect, or use a mock reply."""

    def __init__(self, *, transport=None):
        self.transport = transport

    async def generate(self, prepared, model) -> SemanticModelReply:
        try:
            return await asyncio.wait_for(self._request(prepared, model), timeout=SEMANTIC_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise SemanticModelFailure("semantic provider failed or returned an incomplete response") from None

    async def _request(self, prepared, model):
        binding = model.binding
        system = SEMANTIC_LINK_INSTRUCTIONS + "\nJSON Schema:\n" + json.dumps(SemanticModelOutput.model_json_schema())
        content = json.dumps(prepared.model_payload(), ensure_ascii=False)
        headers = {"Content-Type": "application/json"}
        if binding.provider in {"openai", "openai_compatible"}:
            url = binding.base_url + "/chat/completions"
            headers["Authorization"] = "Bearer " + model.api_key
            body = {"model": binding.model_name, "stream": False, "max_tokens": SEMANTIC_MAX_OUTPUT_TOKENS,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        elif binding.provider == "anthropic":
            url = binding.base_url + "/messages"
            headers.update({"x-api-key": model.api_key, "anthropic-version": "2023-06-01"})
            body = {"model": binding.model_name, "max_tokens": SEMANTIC_MAX_OUTPUT_TOKENS,
                    "system": system, "messages": [{"role": "user", "content": content}]}
        elif binding.provider == "gemini":
            url = binding.base_url + "/models/" + quote(binding.model_name, safe="") + ":generateContent"
            headers["x-goog-api-key"] = model.api_key
            body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": content}]}],
                    "generationConfig": {"maxOutputTokens": SEMANTIC_MAX_OUTPUT_TOKENS, "responseMimeType": "application/json"}}
        else:
            raise SemanticModelFailure("unsupported semantic provider")
        wire = json.dumps(body, ensure_ascii=False).encode()
        if len(wire) > 512 * 1024:
            raise SemanticModelFailure("semantic request exceeds wire budget")
        async with httpx.AsyncClient(timeout=SEMANTIC_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False,
                                     transport=self.transport) as client:
            async with client.stream("POST", url, headers=headers, content=wire) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 512 * 1024:
                        raise SemanticModelFailure("semantic response exceeds wire budget")
                    chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        if binding.provider in {"openai", "openai_compatible"}:
            choices = payload["choices"]
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop" or choices[0]["message"].get("tool_calls"):
                raise SemanticModelFailure("incomplete semantic response")
            content = choices[0]["message"]["content"]
            usage = payload.get("usage", {})
            counts = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
        elif binding.provider == "anthropic":
            if payload.get("stop_reason") != "end_turn" or any(item.get("type") != "text" for item in payload["content"]):
                raise SemanticModelFailure("incomplete semantic response")
            content = "".join(item["text"] for item in payload["content"])
            counts = (payload.get("usage", {}).get("input_tokens"), payload.get("usage", {}).get("output_tokens"))
        else:
            candidates = payload["candidates"]
            if len(candidates) != 1 or candidates[0].get("finishReason") != "STOP" or payload.get("promptFeedback", {}).get("blockReason"):
                raise SemanticModelFailure("incomplete semantic response")
            parts = candidates[0]["content"]["parts"]
            if any(set(item) != {"text"} for item in parts):
                raise SemanticModelFailure("non-text semantic response")
            content = "".join(item["text"] for item in parts)
            counts = (payload.get("usageMetadata", {}).get("promptTokenCount"), payload.get("usageMetadata", {}).get("candidatesTokenCount"))
        if type(content) is not str or not content.strip() or len(content.encode()) > 256 * 1024:
            raise SemanticModelFailure("empty or oversized semantic response")
        valid_usage = all(type(value) is int and value >= 0 for value in counts)
        return SemanticModelReply(content, *(counts if valid_usage else (0, 0)), "provider" if valid_usage else "none")
