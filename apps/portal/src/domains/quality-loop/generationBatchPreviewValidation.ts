import type { GenerationPreview, GenerationSelection } from './types/testDesignGeneration'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual, verifyGenerationPreview } from './testDesignGenerationValidation'

const keys = ['schema', 'selection', 'model_binding', 'policy', 'source_binding_ids', 'source_scope_digest', 'plan_digest', 'reservation', 'messages_hashes'] as const
const integer = (n: unknown, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(n) && Number(n) >= min && Number(n) <= max
function requireValue(value: unknown): asserts value { if (!value) throw new Error('Complete batch preview could not be verified') }

export async function verifyBatchGenerationPreview(value: unknown, selection: GenerationSelection): Promise<GenerationPreview> {
  const v = verifyGenerationPreview(value, selection, 'batch'), plan = v.batch_planning, request = v.request
  requireValue(plan && Object.keys(v).length === 14 && Object.keys(plan).length === 15
    && plan.schema === 'nasus.test-design-batch-planning.v1' && generationEqual(plan.selection, selection)
    && plan.input_digest === request.input_digest && plan.planning_digest === request.execution.plan_digest
    && generationDigest(plan.plan_digest) && generationEqual(plan.policy, v.policy) && generationEqual(plan.reservation, v.reservation)
    && plan.source_scope_digest === request.execution.source_scope_digest && generationEqual(plan.source_binding_ids, request.execution.source_binding_ids)
    && plan.generation_authorized === false && plan.execution_authorized === false
    && Array.isArray(plan.remaining_gates) && generationEqual(plan.remaining_gates, v.remaining_gates)
    && plan.model_binding.config_id === request.model_config_id && plan.model_binding.config_digest === request.model_config_digest
    && Object.keys(plan.model_binding).length === 5 && plan.model_binding.provider === v.provider
    && plan.model_binding.model_name === v.model_name && plan.model_binding.base_url === v.destination
    && Array.isArray(plan.batches) && plan.batches.length === v.call_count
    && Array.isArray(plan.messages_hashes) && plan.messages_hashes.length === v.call_count && plan.messages_hashes.every(generationDigest)
    && new Set(plan.batches.map((b) => b.batch_digest)).size === v.call_count)
  const capacity = Math.min(selection.budget.max_input_tokens_per_call, v.policy.context_tokens - selection.budget.max_output_tokens_per_call)
  for (const [index, batch] of plan.batches.entries()) requireValue(Object.keys(batch).length === 7
    && generationDigest(batch.batch_digest) && batch.sequence === index && integer(batch.estimated_input_tokens, 1, capacity)
    && integer(batch.owned_obligation_count, 1, 32768) && integer(batch.local_constraint_count, 0, 32768)
    && integer(batch.global_rule_count, 0, 32768) && integer(batch.selected_fact_count, 0, 32768))
  requireValue(plan.batches.reduce((sum, batch) => sum + batch.estimated_input_tokens, 0) === v.reservation.estimated_input_tokens
    && await canonicalDigest(v.policy) === request.execution.policy_digest
    && await canonicalDigest(Object.fromEntries(keys.map((key) => [key, plan[key]]))) === request.execution.plan_digest)
  return v
}
