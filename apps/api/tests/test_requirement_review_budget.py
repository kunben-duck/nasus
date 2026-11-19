"""Offline tests for the explicit retained adapter, not production live review."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from apps.api.app.application.platform.model_execution_profiles import ModelExecutionBinding
from apps.api.app.application.quality_loop.generation_budget import GenerationBudgetInvalid, GenerationBudgetLimits, GenerationModelPolicy
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.infrastructure.llm.requirement_review_budget import RetainedRequirementReviewModel


def test_retained_adapter_has_no_chat_fallback_or_dispatch_from_preview():
    model = RetainedRequirementReviewModel()
    with pytest.raises(GenerationBudgetInvalid, match="exact config"):
        model.prepare()
    with pytest.raises(GenerationBudgetInvalid, match="one-shot sender"):
        asyncio.run(model.evaluate({}, {"dispatch": True, "usdNanos": 0}))


@pytest.fixture
def plan_args(tmp_path, monkeypatch):
    # Genuine local policy resolver and tokenizer; no network/cache dependency.
    from tokenizers import Tokenizer, models, pre_tokenizers
    tok = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    asset = tmp_path / "tokenizer.json"
    tok.save(str(asset))
    profile_path = tmp_path / "admin-policy.json"
    monkeypatch.setenv("NASUS_GENERATION_MODEL_POLICIES", str(profile_path))

    def make(host="unit.invalid", model="review-unit", **changes):
        binding = ModelExecutionBinding("saved-unit", "openai_compatible", model, "https://" + host + "/v1", "sha256:" + "a" * 64)
        policy = GenerationModelPolicy(**({"policy_id": "unit-policy", "revision": "r1", "config_id": binding.config_id,
            "provider": binding.provider, "model_name": model, "base_url": binding.base_url, "currency": "USD",
            "context_tokens": 32768, "max_output_tokens": 16384, "input_nanos_per_token": 3,
            "output_nanos_per_token": 7, "framing_tokens": 32, "tokenizer_kind": "huggingface_json",
            "tokenizer_id": "local-unit", "tokenizer_digest": "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()} | changes))
        profile = policy.model_dump(mode="json")
        profile_path.write_text(json.dumps({"schema": "nasus.generation-model-policies.v1",
            "profiles": [{"policy": profile, "tokenizer_path": asset.name}]}))
        return {"acceptance_id": "test-run", "payload": {"project_id": "p", "version_id": "v", "revision_id": "r",
            "invocation_id": "cmd-1", "evidence": [{"ref": "requirement:one", "text": "完整 evidence"}]},
            "binding": binding, "expected_config_id": binding.config_id, "expected_config_digest": binding.config_digest,
            "approved_policy_digest": acceptance_digest(profile), "limits": GenerationBudgetLimits(currency="USD", max_calls=1,
                max_reserved_tokens=35000, max_reserved_cost_nanos=1000000, max_input_tokens_per_call=30000,
                max_output_tokens_per_call=2048)}
    return make


@pytest.mark.parametrize("host,model,disabled", [("api.deepseek.com", "deepseek-v4-flash", True),
    ("api.deepseek.com", "deepseek-reasoner", False), ("proxy.example", "deepseek-v4-flash", False),
    ("api.deepseek.com.evil.example", "deepseek-v4-flash", False)])
def test_plan_uses_final_wire_and_full_cost_envelope(plan_args, host, model, disabled):
    args = plan_args(host, model)
    plan = RetainedRequirementReviewModel.plan_budget(**args)
    m, body = json.loads(plan.manifest), json.loads(plan.wire)
    assert m["bodyBytes"] == len(plan.wire) and m["bodySha256"] == hashlib.sha256(plan.wire).hexdigest()
    assert m["reservation"]["reserved_cost_nanos"] == 32768 * 3 + 2048 * 7
    assert m["reservation"]["cost_basis"] == "operator_rate_ceiling_not_provider_invoice"
    assert m["binding"]["config_digest"] == args["expected_config_digest"] and m["policyDigest"] == args["approved_policy_digest"]
    assert body["max_tokens"] == 2048 and body["stream"] is False
    assert body.get("thinking") == ({"type": "disabled"} if disabled else None)
    assert json.loads(body["messages"][1]["content"]) == args["payload"]
    assert "requirement:one" not in repr(plan)
    assert RetainedRequirementReviewModel.plan_budget(**args) == plan
    args["payload"]["evidence"][0]["text"] += "!"
    assert RetainedRequirementReviewModel.plan_budget(**args).request_digest != plan.request_digest


@pytest.mark.parametrize("change", ["config_id", "config_digest", "policy", "price", "endpoint", "missing",
    "currency", "multiple_calls", "output_cap", "cost_cap", "token_cap", "malformed_id", "wire_cap"])
def test_cannot_plan_unapproved_or_out_of_envelope_request(plan_args, monkeypatch, change):
    args = plan_args()
    if change == "config_id":
        args["expected_config_id"] = "different"
    elif change == "config_digest":
        args["binding"] = replace(args["binding"], config_digest="sha256:" + "b" * 64)
    elif change == "policy":
        args["approved_policy_digest"] = None
    elif change == "price":
        plan_args(input_nanos_per_token=0, output_nanos_per_token=0)
    elif change == "endpoint":
        args["binding"] = replace(args["binding"], base_url="https://other.invalid/v1")
    elif change == "missing":
        monkeypatch.delenv("NASUS_GENERATION_MODEL_POLICIES")
    elif change == "malformed_id":
        del args["payload"]["invocation_id"]
    elif change == "wire_cap":
        args["payload"]["text"] = "x" * (4 * 1024 * 1024)
    else:
        update = {"currency": {"currency": "CNY"}, "multiple_calls": {"max_calls": 2},
            "output_cap": {"max_output_tokens_per_call": 17000}, "cost_cap": {"max_reserved_cost_nanos": 1},
            "token_cap": {"max_reserved_tokens": 1024}}[change]
        args["limits"] = args["limits"].model_copy(update=update)
    with pytest.raises(GenerationBudgetInvalid):
        RetainedRequirementReviewModel.plan_budget(**args)


def test_exact_python_plan_reserves_in_retained_node_ledger(plan_args, tmp_path):
    plan = RetainedRequirementReviewModel.plan_budget(**plan_args())
    directory = tmp_path / "test-run"
    directory.mkdir()
    (directory / "unit-manifest").write_bytes(plan.manifest)
    (directory / "unit-wire").write_bytes(plan.wire)
    root = Path(__file__).resolve().parents[3]
    subprocess.run(["node", str(root / "tests/unit/realworld-retained-budget.cjs"), "m2-plan",
        str(directory), plan.request_digest], check=True, timeout=10)
