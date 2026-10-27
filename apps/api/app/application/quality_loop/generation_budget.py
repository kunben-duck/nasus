"""Operator-pinned tokenization/pricing, independent of model credentials."""
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .test_design_output import Digest, Id


class GenerationBudgetInvalid(ValueError):
    pass


class GenerationBudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    currency: Literal["USD", "CNY"]
    max_calls: int = Field(strict=True, ge=1, le=64)
    max_reserved_tokens: int = Field(strict=True, ge=1024, le=64000000)
    max_reserved_cost_nanos: int = Field(strict=True, ge=1, le=9000000000000000)
    max_input_tokens_per_call: int = Field(strict=True, ge=512, le=1000000)
    max_output_tokens_per_call: int = Field(strict=True, ge=512, le=32768)


class GenerationModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy_id: Id
    revision: Id
    config_id: Id
    provider: Literal["openai", "openai_compatible", "anthropic", "gemini"]
    model_name: str = Field(min_length=1, max_length=256)
    base_url: str = Field(min_length=1, max_length=2048)
    currency: Literal["USD", "CNY"]
    context_tokens: int = Field(strict=True, ge=1024, le=1000000)
    max_output_tokens: int = Field(strict=True, ge=512, le=32768)
    input_nanos_per_token: int = Field(strict=True, ge=0, le=1000000000)
    output_nanos_per_token: int = Field(strict=True, ge=0, le=1000000000)
    framing_tokens: int = Field(strict=True, ge=1, le=8192)
    tokenizer_kind: Literal["tiktoken", "huggingface_json"]
    tokenizer_id: Id
    tokenizer_digest: Digest


class GenerationTokenCounterPort(Protocol):
    policy: GenerationModelPolicy
    def count(self, system: str, content: str) -> int: ...


class GenerationModelPolicyPort(Protocol):
    def resolve(self, binding) -> GenerationTokenCounterPort: ...


def reserve_generation_budget(policy: GenerationModelPolicy, limits: GenerationBudgetLimits, counts):
    if policy.currency != limits.currency or limits.max_output_tokens_per_call > policy.max_output_tokens:
        raise GenerationBudgetInvalid("currency or output limit differs from the operator policy")
    capacity = min(limits.max_input_tokens_per_call, policy.context_tokens - limits.max_output_tokens_per_call)
    if not counts or any(type(count) is not int or not 0 < count <= capacity for count in counts):
        raise GenerationBudgetInvalid("generation input does not fit the model token budget")
    # Reserve the whole configured context envelope, not an optimistic local
    # estimate. Provider usage is authoritative only after a successful call.
    tokens_per_call = policy.context_tokens + limits.max_output_tokens_per_call
    cost_per_call = policy.context_tokens * policy.input_nanos_per_token + limits.max_output_tokens_per_call * policy.output_nanos_per_token
    if (len(counts) > limits.max_calls or len(counts) * tokens_per_call > limits.max_reserved_tokens
            or len(counts) * cost_per_call > limits.max_reserved_cost_nanos):
        raise GenerationBudgetInvalid("complete generation exceeds the confirmed call, token or cost envelope; no batch was dropped")
    return {"currency": policy.currency, "call_count": len(counts), "estimated_input_tokens": sum(counts),
        "reserved_input_tokens_per_call": policy.context_tokens,
        "max_output_tokens_per_call": limits.max_output_tokens_per_call,
        "reserved_tokens": len(counts) * tokens_per_call, "reserved_cost_nanos": len(counts) * cost_per_call,
        "count_basis": "local_tokenizer_with_operator_framing", "cost_basis": "operator_rate_ceiling_not_provider_invoice"}


def verify_generation_usage(policy, limits, input_tokens, output_tokens):
    if (type(input_tokens) is not int or type(output_tokens) is not int or input_tokens <= 0 or output_tokens <= 0
            or input_tokens > min(limits.max_input_tokens_per_call, policy.context_tokens - limits.max_output_tokens_per_call)
            or output_tokens > min(limits.max_output_tokens_per_call, policy.max_output_tokens)):
        raise GenerationBudgetInvalid("provider usage missing or outside the reserved envelope; retain reservation and do not retry")
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
        "cost_nanos_at_policy_rates": input_tokens * policy.input_nanos_per_token + output_tokens * policy.output_nanos_per_token,
        "currency": policy.currency, "usage_source": "provider", "invoice_verified": False}
