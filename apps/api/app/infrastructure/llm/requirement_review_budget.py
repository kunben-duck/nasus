"""Offline M2 plan, NOT a binding quote, billing receipt or permission to send."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from urllib.parse import urlsplit

from ...application.platform.model_execution_profiles import ModelExecutionBinding
from ...application.quality_loop.generation_batch_ledger import BatchModelBinding
from ...application.quality_loop.generation_budget import GenerationBudgetInvalid, GenerationBudgetLimits, reserve_generation_budget
from ...application.quality_loop.requirement_review_models import RequirementAssessment
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .generation_token_budget import ConfiguredGenerationModelPolicies
from .requirement_review_model import MAX_OUTPUT_TOKENS, PROMPT
from .test_design_model import HTTPTestDesignModel


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class M2BudgetPlan:
    manifest: bytes
    wire: bytes = field(repr=False)

    @property
    def request_digest(self):
        return hashlib.sha256(self.manifest).hexdigest()


class RetainedRequirementReviewModel:
    """Opt-in retained planning only. Never delegates to the live chat adapter."""

    @staticmethod
    def plan_budget(*, acceptance_id, payload, binding, expected_config_id, expected_config_digest,
                    approved_policy_digest, limits):
        return plan_review(acceptance_id=acceptance_id, payload=payload, binding=binding,
            expected_config_id=expected_config_id, expected_config_digest=expected_config_digest,
            approved_policy_digest=approved_policy_digest, limits=limits,
            system=PROMPT + "\n" + _json(RequirementAssessment.model_json_schema()),
            prompt_version="nasus.requirement-review.v4", max_review_output=MAX_OUTPUT_TOKENS)

    def prepare(self):
        raise GenerationBudgetInvalid("Retained M2 blocked: exact config, consent and ledger are not wired")

    async def evaluate(self, payload, prepared):
        raise GenerationBudgetInvalid("Retained M2 blocked: no ledger-bound exact-config one-shot sender")


def plan_review(*, acceptance_id, payload, binding: ModelExecutionBinding, expected_config_id,
                expected_config_digest, approved_policy_digest, limits: GenerationBudgetLimits,
                system, prompt_version, max_review_output):
    """Take only the public binding (never ResolvedModelExecution or credentials).

    Pins/limits must come from trusted M2 selection, NOT from review content.
    No approval is inherited from a test-design job or isolated fixture.
    """
    if not isinstance(binding, ModelExecutionBinding):
        raise GenerationBudgetInvalid("exact public saved-model binding required")
    pin = BatchModelBinding.model_validate(asdict(binding))
    if pin.config_id != expected_config_id or pin.config_digest != expected_config_digest:
        raise GenerationBudgetInvalid("saved config ID/digest differs from the approved selection")
    if not isinstance(approved_policy_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", approved_policy_digest):
        raise GenerationBudgetInvalid("approved M2 pricing/tokenizer policy digest required")
    base = urlsplit(pin.base_url)
    if (pin.provider not in {"openai", "openai_compatible"} or base.scheme != "https"
            or not base.hostname or base.username is not None or base.password is not None
            or base.query or base.fragment or pin.base_url.endswith("/") or "\\" in pin.base_url
            or any(ord(ch) <= 32 or ord(ch) == 127 for ch in pin.base_url)):
        raise GenerationBudgetInvalid("unsupported M2 exact-wire destination")
    if (not isinstance(acceptance_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", acceptance_id)
            or not isinstance(payload, dict) or not isinstance(payload.get("invocation_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}", payload["invocation_id"])):
        raise GenerationBudgetInvalid("retained acceptance and stable invocation ID required")

    limits = GenerationBudgetLimits.model_validate(limits.model_dump())
    if limits.currency != "USD" or limits.max_calls != 1 or limits.max_output_tokens_per_call > max_review_output:
        raise GenerationBudgetInvalid("M2 requires a single capped USD call")
    counter = ConfiguredGenerationModelPolicies().resolve(binding)
    policy = counter.policy
    if acceptance_digest(policy.model_dump(mode="json")) != approved_policy_digest:
        raise GenerationBudgetInvalid("no matching approved M2 pricing/tokenizer policy digest")
    content = _json(payload)
    body = {"model": pin.model_name, "stream": False, "max_tokens": limits.max_output_tokens_per_call,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    if (pin.provider == "openai_compatible" and base.hostname == "api.deepseek.com"
            and (pin.model_name.startswith("deepseek-v4") or pin.model_name == "deepseek-flash")):
        body["thinking"] = {"type": "disabled"}
    wire = _json(body).encode()
    if len(wire) > HTTPTestDesignModel.MAX_WIRE_BYTES:
        raise GenerationBudgetInvalid("complete review exceeds native wire limit; no truncation")
    reservation = reserve_generation_budget(policy, limits, [counter.count(system, content)])
    manifest = {"schema": "nasus.m2-exact-wire.v1", "acceptanceId": acceptance_id, "operationId": payload["invocation_id"],
                "promptVersion": prompt_version, "binding": pin.model_dump(mode="json"), "policyDigest": approved_policy_digest,
                "limits": limits.model_dump(mode="json"), "reservation": reservation,
                "method": "POST", "url": pin.base_url + "/chat/completions", "contentType": "application/json",
                "bodySha256": hashlib.sha256(wire).hexdigest(), "bodyBytes": len(wire),
                "maxAttempts": 1, "followRedirects": False, "fallback": False}
    return M2BudgetPlan(_json(manifest).encode(), wire)
