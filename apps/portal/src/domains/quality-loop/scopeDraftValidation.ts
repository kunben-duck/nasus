import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import type { ScopeDraftPreview, ScopeDraftSelection } from './scopeDraftApi'

export function requireScopeDraft(valid: unknown): asserts valid {
  if (!valid) throw new Error('Scope model draft could not be verified')
}
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max
const id = (v: unknown) => typeof v === 'string' && !!v && v.length <= 256

export async function verifyScopeDraftPreview(value: unknown, selection: ScopeDraftSelection): Promise<ScopeDraftPreview> {
  const v = value as ScopeDraftPreview, r = v?.request, plan = v?.plan, b = plan?.reservation, p = plan?.policy, m = plan?.model_binding
  const budget = selection.budget
  requireScopeDraft(r && plan && p && b && m && v.review_required === true && v.generation_authorized === false
    && Object.keys(r).length === Object.keys(selection).length + 3
    && Object.entries(selection).every(([key, item]) => generationEqual(r[key as keyof typeof r], item))
    && [r.input_digest, r.model_config_digest, r.plan_digest, plan.messages_hash, plan.source_scope_digest, p.tokenizer_digest].every(generationDigest)
    && r.input_digest === plan.input_digest && generationEqual(plan.budget, budget) && plan.timeout_seconds === 120
    && m.config_id === selection.model_config_id && m.config_digest === r.model_config_digest
    && m.provider === v.provider && m.model_name === v.model_name && m.base_url === v.destination
    && p.config_id === m.config_id && p.provider === m.provider && p.model_name === m.model_name && p.base_url === m.base_url
    && ['openai', 'openai_compatible', 'anthropic', 'gemini'].includes(v.provider)
    && [v.model_name, p.policy_id, p.revision, p.tokenizer_id].every(id)
    && ['tiktoken', 'huggingface_json'].includes(p.tokenizer_kind) && integer(p.framing_tokens, 1, 8192)
    && integer(p.context_tokens, 1024, 1000000) && integer(p.max_output_tokens, 512, 32768)
    && integer(p.input_nanos_per_token, 0, 1e9) && integer(p.output_nanos_per_token, 0, 1e9)
    && ['USD', 'CNY'].includes(budget.currency) && p.currency === budget.currency && b.currency === budget.currency
    && integer(budget.max_calls, 1, 64) && integer(budget.max_input_tokens_per_call, 512, 1000000)
    && integer(budget.max_output_tokens_per_call, 512, p.max_output_tokens) && integer(budget.max_reserved_tokens, 1024, 64000000)
    && integer(budget.max_reserved_cost_nanos, 1, 9e15)
    && Array.isArray(plan.source_binding_ids) && plan.source_binding_ids.length > 0 && plan.source_binding_ids.every(id)
    && generationEqual(plan.source_binding_ids, [...new Set(plan.source_binding_ids)].sort())
    && b.call_count === 1 && b.count_basis === 'local_tokenizer_with_operator_framing'
    && b.cost_basis === 'operator_rate_ceiling_not_provider_invoice'
    && integer(b.estimated_input_tokens, 1, Math.min(budget.max_input_tokens_per_call, p.context_tokens - budget.max_output_tokens_per_call))
    && b.reserved_input_tokens_per_call === p.context_tokens && b.max_output_tokens_per_call === budget.max_output_tokens_per_call
    && b.reserved_tokens === p.context_tokens + budget.max_output_tokens_per_call && b.reserved_tokens <= budget.max_reserved_tokens
    && integer(b.reserved_cost_nanos) && b.reserved_cost_nanos <= budget.max_reserved_cost_nanos
    && b.reserved_cost_nanos === p.context_tokens * p.input_nanos_per_token + budget.max_output_tokens_per_call * p.output_nanos_per_token
    && await canonicalDigest(plan) === r.plan_digest)
  const url = new URL(v.destination)
  requireScopeDraft(url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash)
  return v
}
