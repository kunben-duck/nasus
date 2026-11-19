import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from apps.api.app.infrastructure.llm import gateway as gateway_module
from apps.api.app.infrastructure.llm import requirement_review_model as review_module
from apps.api.app.infrastructure.llm.gateway import LLMGateway, LLMReply
from apps.api.app.infrastructure.llm.requirement_review_model import RequirementReviewModel
from apps.api.app.application.platform.model_settings import ModelProviderProfile, StudioSettings
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


def test_non_retained_live_prepare_and_evaluate_preserve_v3_contract(monkeypatch):
    # Exercise real prepare/binding checks, but never inspect the account environment.
    monkeypatch.setattr(review_module, "os", SimpleNamespace(environ={}))
    monkeypatch.setenv("NASUS_GENERATION_MODEL_POLICIES", "/nonexistent/retained-policy")
    settings = StudioSettings(runtime_mode="live", model_name="unit-chat",
        model_profiles={"chat": ModelProviderProfile(route="chat", model_name="unit-chat")})
    secret = Mock(return_value="unit-only")
    reply = LLMReply(json.dumps(proposal()), "openai", settings.model_name, "live", "unit",
        input_tokens=12, output_tokens=6, usage_source="provider", llm_call_id="unit-call")
    gateway = SimpleNamespace(generate_reply=AsyncMock(return_value=reply))
    model = RequirementReviewModel(gateway, lambda: settings, secret)
    prepared = model.prepare()
    binding, snapshot, selected_secret = prepared
    secret.assert_called_once_with("chat")
    assert snapshot == settings and snapshot is not settings
    assert selected_secret == "unit-only" and binding["prompt_version"] == "nasus.requirement-review.v3"

    payload = {"project_id": "ordinary-project", "version_id": "v", "revision_id": "r",
        "invocation_id": "command", "evidence": [{"ref": "requirement:one"}]}
    assessment, receipt = asyncio.run(model.evaluate(payload, prepared))
    assert assessment.model_dump(mode="json") == proposal()
    assert receipt == {**binding, "llm_call_id": "unit-call", "input_tokens": 12, "output_tokens": 6, "usage_source": "provider"}
    gateway.generate_reply.assert_awaited_once()
    call = gateway.generate_reply.await_args.kwargs
    assert call["settings"] is snapshot and call["custom_api_key"] == selected_secret
    assert call["system_prompt"] == review_module.PROMPT + "\n" + json.dumps(RequirementAssessment.model_json_schema())
    assert call["user_message"] == json.dumps(payload, ensure_ascii=False)
    assert (call["max_output_tokens"], call["request_timeout_seconds"]) == (16384, 105)
    context = call["call_context"]
    assert (context.purpose, context.prompt_id, context.prompt_version, context.tool_invocation_id) == (
        "quality.requirement.evaluate", "requirement_review", "nasus.requirement-review.v3", "command")

    secret.return_value = "unit-only-rotated"
    with pytest.raises(ValueError, match="Review model changed"):
        asyncio.run(model.evaluate(payload, prepared))
    gateway.generate_reply.assert_awaited_once()
