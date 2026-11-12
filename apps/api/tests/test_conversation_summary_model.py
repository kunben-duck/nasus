import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.app.infrastructure.llm.conversation_summary_model import ConversationSummaryModel, SUMMARY_PROMPT
from apps.api.app.infrastructure.llm.gateway import LLMGateway
from apps.api.app.domain.agent.conversation_memory import ConversationHistory
from apps.api.app.infrastructure.llm.conversation_token_budget import model_budget


class Gateway:
    def __init__(self, mode="live", content=None):
        self.calls = []
        self.mode = mode
        self.content = content or '{"constraints":[{"text":"不要自动发布","origin":"user_statement","refs":["message:m1"]}]}'

    async def generate_reply(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(mode=self.mode, content=self.content, provider="openai_compatible", model_name="test-chat",
            input_tokens=800, output_tokens=100, usage_source="provider", llm_call_id="call-1")


def adapter(gateway, mode="live"):
    settings = StudioSettings(model_name="test-chat", model_provider="openai_compatible", runtime_mode=mode)
    return ConversationSummaryModel(gateway, lambda: settings, lambda _: "private-key"), settings


def test_summary_uses_audited_model_purpose_and_never_stores_credential():
    gateway = Gateway()
    model, _ = adapter(gateway)
    digest, usage = asyncio.run(model.summarize({"conversation_id": "c1", "messages": []}, model.binding()))
    assert digest.constraints[0].refs == ["message:m1"]
    assert usage["llm_call_id"] == "call-1" and usage["input_tokens"] == 800
    assert gateway.calls[0]["call_context"].purpose == "agent.conversation_summary"
    assert gateway.calls[0]["max_output_tokens"] == 4096
    assert "private-key" not in str(model.binding()) + str(usage)
    assert "untrusted reference data" in SUMMARY_PROMPT


@pytest.mark.parametrize("mode,content", [("fallback", None), ("live", "not JSON")])
def test_summary_rejects_fallback_and_invalid_output(mode, content):
    model, _ = adapter(Gateway(mode, content))
    with pytest.raises((RuntimeError, ValueError)):
        asyncio.run(model.summarize({"conversation_id": "c1"}, model.binding()))


def test_model_change_between_queue_and_execution_never_calls_new_model():
    gateway = Gateway()
    model, settings = adapter(gateway)
    binding = model.binding()
    settings.model_name = "changed"
    with pytest.raises(ValueError, match="summary_model_changed"):
        asyncio.run(model.summarize({}, binding))
    assert not gateway.calls


def test_per_model_output_reserve_cost_and_policy_change_are_explicit(monkeypatch):
    gateway = Gateway()
    model, settings = adapter(gateway)
    original_binding = model.binding()
    monkeypatch.setenv("NASUS_MEMORY_MODEL_BUDGETS", '{"test-chat":{"context_window":24576,'
        '"summary_output_tokens":8192,"safety_reserve":1024,'
        '"input_usd_per_million":1,"output_usd_per_million":2}}')
    assert model.binding() != original_binding
    assert model_budget(settings).input_limit == 15360
    _, usage = asyncio.run(model.summarize({"conversation_id": "c1"}, model.binding()))
    assert gateway.calls[0]["max_output_tokens"] == 8192
    assert usage["estimated_cost_usd"] == "0.001"


def test_native_provider_payloads_keep_history_roles_and_single_current_question():
    history = ConversationHistory("summary", [{"role": "user", "content": "old"},
        {"role": "assistant", "content": "answer"}, {"role": "user", "content": "current"}])
    openai = LLMGateway._chat_messages("system", "current", "facts", history)
    anthropic = LLMGateway._dialogue_messages("current", "facts", history)
    gemini = LLMGateway._gemini_messages("current", "facts", history)
    assert [item["role"] for item in openai] == ["system", "user", "user", "assistant", "user"]
    assert anthropic == openai[1:]
    assert [item["role"] for item in gemini] == ["user", "user", "model", "user"]
    assert sum(item["content"] == "current" for item in openai) == 1
