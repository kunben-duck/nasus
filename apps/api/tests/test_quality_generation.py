import asyncio
import json

import pytest

from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.app.application.quality_loop.generation import (
    QUALITY_GENERATION_PROMPTS,
    QualityGenerationError,
    QualityGenerationRequest,
    fallback_generation_output,
    validate_generation_output,
)
from apps.api.app.infrastructure.llm.gateway import LLMReply
from apps.api.app.infrastructure.llm.quality_generation import LLMQualityGenerationAdapter
from apps.api.app.domain.platform.prompt_registry import PromptDefinition


class FakeLLMGateway:
    def __init__(self, reply: LLMReply) -> None:
        self.reply = reply
        self.calls = []

    async def generate_reply(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class FakePromptRegistry:
    def get_active(self, prompt_id: str) -> PromptDefinition:
        return PromptDefinition(
            prompt_id=prompt_id,
            name="Test active prompt",
            version="1.1.0",
            purpose="Test runtime prompt resolution.",
            input_schema_ref="test-input/v1",
            output_schema_ref="quality-scenario-output/v1",
            safety_rules_ref="test-safety/v1",
            rollback_to="1.0.0",
            system_template="ACTIVE REGISTRY PROMPT",
        )


def generation_request(stage="scenarios") -> QualityGenerationRequest:
    return QualityGenerationRequest(
        stage=stage,
        project_id="project_quality",
        us_id="us_checkout",
        task_context={
            "id": "task_context_checkout",
            "object_refs": ["context_object:checkout"],
            "summary": "Checkout submission and payment authorization context.",
        },
        quality_profile={
            "id": "quality_profile_checkout",
            "risk_score": 82,
            "risk_drivers": ["payment authorization failure"],
        },
    )


def test_live_quality_generation_is_schema_validated_and_audited():
    payload = {
        "scenarios": [
            {
                "scenario_id": "scenario_checkout_success",
                "title": "Authorize a valid payment",
                "category": "main_flow",
                "objective": "Complete checkout after successful authorization.",
                "preconditions": ["A valid basket and payment method exist."],
                "linked_context_objects": ["context_object:checkout"],
                "risk_reason": "Checkout is a release-critical path.",
            }
        ]
    }
    gateway = FakeLLMGateway(
        LLMReply(
            content=json.dumps(payload),
            provider="openai_compatible",
            model_name="quality-model",
            mode="live",
            reason="provider_success",
        )
    )
    adapter = LLMQualityGenerationAdapter(
        llm=gateway,  # type: ignore[arg-type]
        settings_provider=StudioSettings,
        custom_api_key_provider=lambda route: "secret" if route == "chat" else "",
        fail_closed=True,
    )

    result = asyncio.run(adapter.generate(generation_request()))

    assert result.structured_output == payload
    assert result.generation.mode == "live"
    assert result.generation.prompt_id == "quality.scenario.generate"
    assert result.generation.prompt_version == "1.0.0"
    assert result.generation.input_context_hash.startswith("sha256:")
    assert "JSON Schema:" in gateway.calls[0]["system_prompt"]


def test_quality_generation_uses_active_prompt_registry_version():
    payload = {
        "scenarios": [
            {
                "scenario_id": "scenario_registry",
                "title": "Registry prompt",
                "category": "main_flow",
                "objective": "Verify active prompt resolution.",
                "preconditions": [],
                "linked_context_objects": ["context_object:checkout"],
                "risk_reason": "Prompt provenance must remain auditable.",
            }
        ]
    }
    gateway = FakeLLMGateway(
        LLMReply(
            content=json.dumps(payload),
            provider="openai_compatible",
            model_name="quality-model",
            mode="live",
            reason="provider_success",
        )
    )
    adapter = LLMQualityGenerationAdapter(
        llm=gateway,  # type: ignore[arg-type]
        settings_provider=StudioSettings,
        custom_api_key_provider=lambda _route: "secret",
        fail_closed=True,
        prompt_registry=FakePromptRegistry(),  # type: ignore[arg-type]
    )

    result = asyncio.run(adapter.generate(generation_request()))

    assert result.generation.prompt_version == "1.1.0"
    assert "ACTIVE REGISTRY PROMPT" in gateway.calls[0]["system_prompt"]
    assert gateway.calls[0]["call_context"].prompt_version == "1.1.0"


def test_production_quality_generation_fails_closed_on_provider_fallback():
    gateway = FakeLLMGateway(
        LLMReply(
            content="{}",
            provider="openai_compatible",
            model_name="quality-model",
            mode="fallback",
            reason="provider_error",
        )
    )
    adapter = LLMQualityGenerationAdapter(
        llm=gateway,  # type: ignore[arg-type]
        settings_provider=StudioSettings,
        custom_api_key_provider=lambda route: "secret",
        fail_closed=True,
    )

    with pytest.raises(QualityGenerationError, match="requires a live model provider"):
        asyncio.run(adapter.generate(generation_request()))


def test_local_quality_generation_uses_explicit_fallback_for_invalid_output():
    gateway = FakeLLMGateway(
        LLMReply(
            content="not-json",
            provider="openai_compatible",
            model_name="quality-model",
            mode="live",
            reason="provider_success",
        )
    )
    adapter = LLMQualityGenerationAdapter(
        llm=gateway,  # type: ignore[arg-type]
        settings_provider=StudioSettings,
        custom_api_key_provider=lambda route: "secret",
        fail_closed=False,
    )

    result = asyncio.run(adapter.generate(generation_request()))

    assert result.structured_output["scenarios"]
    assert result.generation.mode == "fallback"
    assert result.generation.reason == "invalid_structured_output"


def test_prompt_registry_has_versioned_v1_contracts():
    assert {
        stage: (definition.prompt_id, definition.prompt_version, definition.output_schema_ref)
        for stage, definition in QUALITY_GENERATION_PROMPTS.items()
    } == {
        "scope": ("quality.scope.generate", "1.0.0", "quality-scope-output/v1"),
        "scenarios": ("quality.scenario.generate", "1.0.0", "quality-scenario-output/v1"),
        "verification_plan": (
            "quality.plan.generate",
            "1.0.0",
            "quality-verification-plan-output/v1",
        ),
        "cases": ("quality.case.generate", "1.0.0", "quality-case-output/v1"),
        "automation": ("automation.generate", "1.0.0", "automation-blueprint-output/v1"),
        "change_document": (
            "quality.change-doc.generate",
            "1.0.0",
            "quality-change-document-output/v1",
        ),
    }


def test_automation_generation_contract_accepts_runner_whitelist_and_target_hint():
    payload = fallback_generation_output(
        "automation",
        "us_checkout",
        tool_input={"base_url": "https://staging.example.test"},
    )

    validated = validate_generation_output("automation", payload)

    assert validated["framework"] == "playwright"
    assert validated["default_base_url"] == "https://staging.example.test"
    assert validated["scripts"][0]["linked_case_ids"] == ["case_us_checkout_1"]
    assert [step["action"] for step in validated["scripts"][0]["steps"]] == [
        "goto",
        "assert_visible",
    ]


def test_automation_generation_contract_rejects_unexecutable_or_unsafe_steps():
    with pytest.raises(ValueError, match="click requires field"):
        validate_generation_output(
            "automation",
            {
                "framework": "playwright",
                "scripts": [
                    {
                        "script_id": "script_unsafe",
                        "title": "Unsafe script",
                        "linked_case_ids": ["case_1"],
                        "steps": [{"action": "click"}],
                    }
                ],
                "selector_strategy": "Use stable selectors.",
            },
        )

    with pytest.raises(ValueError, match="Input should be"):
        validate_generation_output(
            "automation",
            {
                "framework": "playwright",
                "scripts": [
                    {
                        "script_id": "script_shell",
                        "title": "Shell escape",
                        "linked_case_ids": ["case_1"],
                        "steps": [{"action": "shell", "value": "rm -rf /"}],
                    }
                ],
                "selector_strategy": "Use stable selectors.",
            },
        )
