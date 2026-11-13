import asyncio
import json
from types import SimpleNamespace

import pytest

from apps.api.app.infrastructure.llm import gateway as gateway_module
from apps.api.app.infrastructure.llm.gateway import LLMGateway, LLMReply
from apps.api.app.infrastructure.llm.requirement_review_model import RequirementReviewModel
from apps.api.app.application.quality_loop.requirement_review_models import RequirementAssessment


def proposal():
    return {"summary": "Clarify ownership", "checks": [{"dimension": dimension, "assessment": "Ownership is unspecified",
        "refs": ["requirement:one"]} for dimension in ("roles", "preconditions", "inputs_outputs", "errors", "verifiability", "conflicts")],
        "questions": [{"question": "Who may edit?", "blocking": True, "rationale": "No actor specified", "refs": ["requirement:one"]}],
        "suggestions": [], "criteria": []}


@pytest.mark.parametrize("mutation", ["unknown_ref", "duplicate_dimension", "no_criteria", "blank"])
def test_invalid_assessment_is_not_semantic_memory(mutation):
    value = proposal()
    if mutation == "unknown_ref":
        value["checks"][0]["refs"] = ["tool:invented"]
    elif mutation == "duplicate_dimension":
        value["checks"][0]["dimension"] = "conflicts"
    elif mutation == "no_criteria":
        value["questions"] = []
    else:
        value["summary"] = "   "
    with pytest.raises(ValueError):
        RequirementAssessment.model_validate(value).validate_refs({"requirement:one"})


@pytest.mark.parametrize("mode,content", [("fallback", json.dumps(proposal())), ("live", "invalid JSON"), ("live", "")])
def test_failed_model_never_becomes_a_review(mode, content):
    async def generate_reply(**kwargs):
        assert kwargs["request_timeout_seconds"] == 105
        assert kwargs["call_context"].tool_invocation_id == "command"
        return LLMReply(content, "openai_compatible", "test", mode, "test")
    model = RequirementReviewModel(SimpleNamespace(generate_reply=generate_reply), None, None)
    prepared = ({"digest": "test"}, None, None)
    model.prepare = lambda: prepared
    with pytest.raises(ValueError):
        asyncio.run(model.evaluate({"project_id": "p", "version_id": "v", "revision_id": "one", "invocation_id": "command",
            "evidence": [{"ref": "requirement:one"}]}, prepared))


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic", "openai_compatible"])
def test_review_timeout_reaches_each_chat_adapter_without_changing_default(monkeypatch, provider):
    timeouts = []
    payloads = []
    class Client:
        def __init__(self, **kwargs):
            timeouts.append(kwargs["timeout"])
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def post(self, *args, **kwargs):
            payloads.append(kwargs["json"])
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "choices": [{"message": {"content": "answer"}}],
                "candidates": [{"content": {"parts": [{"text": "answer"}]}}],
                "content": [{"type": "text", "text": "answer"}],
            })
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", Client)
    method = getattr(LLMGateway(), "_call_" + provider)
    args = {"model_name": "test", "api_key": "test-only", "system_prompt": "system", "user_message": "question",
        "context_snapshot": "", "history_snapshot": ""}
    if provider == "openai_compatible":
        args["base_url"] = "https://example.invalid/v1"
    options = {"thinking_mode": "disabled"} if provider == "openai_compatible" else {}
    asyncio.run(method(**args, request_timeout_seconds=105, **options))
    asyncio.run(method(**args))
    assert timeouts == [105, 45.0]
    assert "thinking" not in payloads[1]
    if provider == "openai_compatible":
        assert payloads[0]["thinking"] == {"type": "disabled"}


def test_review_timeout_is_forwarded_through_custom_dispatch(monkeypatch):
    from apps.api.app.application.platform.model_settings import CustomModelConfig
    gateway = LLMGateway()
    seen = []
    async def call(**kwargs):
        seen.append(kwargs["request_timeout_seconds"])
        assert kwargs["thinking_mode"] == "disabled"
        return "answer"
    monkeypatch.setattr(gateway, "_call_openai_compatible", call)
    asyncio.run(gateway._call_provider(provider="openai_compatible", model_name="test", model_preset="custom",
        custom_model=CustomModelConfig(provider_kind="openai_compatible", base_url="https://example.invalid", model_name="test"),
        custom_api_key="test-only", system_prompt="", user_message="", context_snapshot="", history_snapshot="", request_timeout_seconds=105, thinking_mode="disabled"))
    assert seen == [105]


@pytest.mark.parametrize("host,model,expected", [("api.deepseek.com", "deepseek-v4-flash", {"thinking_mode": "disabled"}),
    ("api.deepseek.com", "deepseek-reasoner", {}), ("proxy.example", "deepseek-v4-flash", {}),
    ("api.deepseek.com.evil.example", "deepseek-v4-flash", {})])
def test_review_vendor_mode_is_scoped_to_supported_endpoint(host, model, expected):
    settings = SimpleNamespace(model_provider="openai_compatible", model_preset="custom", model_name=model,
        custom_model=SimpleNamespace(base_url="https://" + host + "/v1"))
    assert RequirementReviewModel.generation_options(settings) == expected
