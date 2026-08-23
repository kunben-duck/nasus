from apps.api.app.infrastructure.llm.gateway import LLMGateway, ProviderGeneration


def test_provider_generation_prefers_native_usage():
    result = LLMGateway._provider_generation(
        "answer",
        input_tokens=120,
        output_tokens=25,
        input_text="ignored",
    )

    assert result == ProviderGeneration(
        content="answer",
        input_tokens=120,
        output_tokens=25,
        usage_source="provider",
    )


def test_provider_generation_marks_missing_usage_as_estimated():
    result = LLMGateway._provider_generation(
        "eight",
        input_tokens=None,
        output_tokens=None,
        input_text="12345678",
    )

    assert result.input_tokens == 2
    assert result.output_tokens == 2
    assert result.usage_source == "estimated"
