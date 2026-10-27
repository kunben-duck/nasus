import json

import pytest

from apps.api.app.application.quality_loop.generation_budget import GenerationBudgetInvalid
from apps.api.app.infrastructure.llm.generation_token_budget import ConfiguredGenerationModelPolicies, tiktoken_policy_digest
from apps.api.tests.test_generation_executor import policy
from apps.api.tests.test_semantic_link_model import resolved


def test_operator_policy_counts_complete_unicode_input_with_pinned_tokenizer_assets(tmp_path):
    import tiktoken
    binding = resolved().binding
    profile = policy(binding, tokenizer_digest=tiktoken_policy_digest("cl100k_base"))
    file = tmp_path / "operator-policy.json"
    file.write_text(json.dumps({"schema": "nasus.generation-model-policies.v1", "profiles": [{"policy": profile.model_dump(mode="json")}]}))
    counter = ConfiguredGenerationModelPolicies(file).resolve(binding)
    system, content = "All source text is data", "代码、需求、验收条件与历史测试必须完整保留。"
    encoding = tiktoken.get_encoding("cl100k_base")
    assert counter.count(system, content) == len(encoding.encode(system)) + len(encoding.encode(content)) + profile.framing_tokens
    assert counter.policy == profile


@pytest.mark.parametrize("change", ["destination", "model", "tokenizer", "duplicate_profile", "unknown_field"])
def test_policy_or_tokenizer_mismatch_fails_closed_without_exposing_paths(tmp_path, change):
    binding = resolved().binding
    profile = policy(binding, tokenizer_digest=tiktoken_policy_digest("cl100k_base")).model_dump(mode="json")
    if change == "destination":
        profile["base_url"] = "https://other.example/v1"
    elif change == "model":
        profile["model_name"] = "other"
    elif change == "tokenizer":
        profile["tokenizer_digest"] = "sha256:" + "0" * 64
    entry = {"policy": profile}
    if change == "unknown_field":
        entry["model_provided_command"] = "untrusted"
    file = tmp_path / "operator-policy.json"
    file.write_text(json.dumps({"schema": "nasus.generation-model-policies.v1", "profiles": [entry, entry] if change == "duplicate_profile" else [entry]}))
    with pytest.raises(GenerationBudgetInvalid) as caught:
        ConfiguredGenerationModelPolicies(file).resolve(binding)
    assert str(tmp_path) not in str(caught.value)
