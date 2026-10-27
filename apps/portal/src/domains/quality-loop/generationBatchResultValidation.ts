import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual, verifyGenerationArchive } from './testDesignGenerationValidation'
import { verifyGenerationMetadata } from './generationResultMetadata'
import { verifyBatchRecoveryPins } from './generationBatchRecoveryValidation'
import type { GenerationArchive, GenerationJob } from './types/testDesignGeneration'
import type { GenerationBatchArchive } from './types/generationBatchResult'
import type { ScopeArchive } from './types/testDesignScope'

function requireValue(value: unknown): asserts value { if (!value) throw new Error('Complete native batch result could not be verified') }
const keys = (value: unknown, names: string[]) => !!value && typeof value === 'object' && !Array.isArray(value)
  && generationEqual(Object.keys(value).sort(), [...names].sort())
const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max
const ids = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string' && item.length > 0 && item.length <= 128)
  && new Set(value).size === value.length
const timestamp = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value))

async function verifyBatchProvenance(v: GenerationBatchArchive) {
  const r = v.result, m = v.metadata, plan = r.batch_plan, reservation = r.reservation, p = reservation?.policy
  const recovered = r.schema === 'nasus.test-design-result.v4'
  requireValue(keys(v, ['metadata', 'result', 'historical_not_live', 'current_use', 'view_schema', 'view_hash'])
    && v.view_schema === (recovered ? 'nasus.test-design-result-view.v4' : 'nasus.test-design-result-view.v3') && generationDigest(v.view_hash)
    && keys(r, ['schema', 'project_id', 'generation_id', 'invocation_id', 'actor_id', 'request', 'context_pin', 'scope_pin', 'model_binding',
      'reservation', 'batch_plan', 'calls', 'proposal', 'provenance', 'merged_output_hash', 'status', 'mapping_status', 'execution_authorized',
      ...(recovered ? ['recovery_invocation_id', 'recovery_request'] : [])])
    && verifyGenerationMetadata(m) && m.schema === r.schema && m.call_id === null && m.plan_digest === plan?.plan_digest
    && keys(reservation, ['schema_version', 'project_id', 'invocation_id', 'actor_id', 'request', 'model_binding', 'policy', 'plan_digest', 'batches', 'reservation'])
    && reservation.schema_version === 'nasus.test-design-batch-reservation.v1' && reservation.project_id === r.project_id
    && reservation.invocation_id === r.invocation_id && reservation.actor_id === r.actor_id && ids([r.actor_id])
    && generationEqual(reservation.request, r.request) && generationEqual(reservation.model_binding, r.model_binding)
    && r.model_binding.config_id === r.request.model_config_id && r.model_binding.config_digest === r.request.model_config_digest
    && ['openai', 'openai_compatible', 'anthropic', 'gemini'].includes(r.model_binding.provider)
    && keys(r.model_binding, ['config_id', 'config_digest', 'provider', 'model_name', 'base_url'])
    && keys(plan, ['schema', 'input_digest', 'plan_digest', 'batches']) && plan.schema === 'nasus.test-design-batch-plan.v1'
    && plan.input_digest === r.request.input_digest && reservation.plan_digest === plan.plan_digest
    && Array.isArray(plan.batches) && integer(plan.batches.length, 1, 64) && plan.batches.length === m.batch_count
    && Array.isArray(reservation.batches) && reservation.batches.length === m.batch_count
    && Array.isArray(r.calls) && r.calls.length === m.batch_count && Array.isArray(r.provenance) && r.provenance.length === m.batch_count)
  const { view_hash, ...view } = v
  requireValue(await canonicalDigest(view) === view_hash)
  const { plan_digest, ...planBody } = plan
  requireValue(await canonicalDigest(planBody) === plan_digest && await canonicalDigest(p) === r.request.execution.policy_digest)
  const consent = r.request.execution, b = reservation.reservation, limits = consent.budget, count = plan.batches.length
  requireValue(keys(p, ['policy_id', 'revision', 'config_id', 'provider', 'model_name', 'base_url', 'currency', 'context_tokens', 'max_output_tokens',
    'input_nanos_per_token', 'output_nanos_per_token', 'framing_tokens', 'tokenizer_kind', 'tokenizer_id', 'tokenizer_digest'])
    && ['config_id', 'provider', 'model_name', 'base_url'].every((key) => generationEqual(p[key as keyof typeof p], r.model_binding[key as keyof typeof r.model_binding]))
    && integer(p.context_tokens, 1024, 1000000) && integer(p.max_output_tokens, 512, 32768)
    && integer(p.input_nanos_per_token, 0, 1000000000) && integer(p.output_nanos_per_token, 0, 1000000000)
    && integer(limits.max_calls, count, 64) && integer(limits.max_output_tokens_per_call, 512, p.max_output_tokens)
    && integer(limits.max_input_tokens_per_call, 512, 1000000) && limits.currency === p.currency
    && keys(b, ['currency', 'call_count', 'estimated_input_tokens', 'reserved_input_tokens_per_call', 'max_output_tokens_per_call',
      'reserved_tokens', 'reserved_cost_nanos', 'count_basis', 'cost_basis'])
    && b.currency === p.currency && b.call_count === count && b.reserved_input_tokens_per_call === p.context_tokens
    && b.max_output_tokens_per_call === limits.max_output_tokens_per_call
    && b.reserved_tokens === count * (p.context_tokens + limits.max_output_tokens_per_call) && b.reserved_tokens <= limits.max_reserved_tokens
    && b.reserved_cost_nanos === count * (p.context_tokens * p.input_nanos_per_token + limits.max_output_tokens_per_call * p.output_nanos_per_token)
    && integer(b.reserved_cost_nanos) && b.reserved_cost_nanos <= limits.max_reserved_cost_nanos
    && b.count_basis === 'local_tokenizer_with_operator_framing' && b.cost_basis === 'operator_rate_ceiling_not_provider_invoice')
  const planning = { schema: 'nasus.test-design-batch-planning.v1',
    selection: { project_id: r.project_id, scope_revision_id: r.request.scope_revision_id, scope_artifact_hash: r.request.scope_artifact_hash,
      model_config_id: r.request.model_config_id, budget: limits }, model_binding: r.model_binding, policy: p,
    source_binding_ids: consent.source_binding_ids, source_scope_digest: consent.source_scope_digest, plan_digest,
    reservation: b, messages_hashes: reservation.batches.map((item) => item.messages_hash) }
  requireValue(await canonicalDigest(planning) === consent.plan_digest && ids(consent.source_binding_ids)
    && consent.source_binding_ids.length > 0 && generationEqual(consent.source_binding_ids, [...consent.source_binding_ids].sort())
    && generationDigest(consent.source_scope_digest) && consent.purpose === 'draft_test_design_source_egress')
  const rows = new Map(r.proposal.coverage.rows.map((row) => [row.row_id, row])), ownedRows = new Set<string>()
  const cases = new Map(r.proposal.cases.map((item) => [item.case_id, item])), gaps = new Map(r.proposal.gaps.map((item) => [item.gap_id, item]))
  const seenCases = new Set<string>(), seenGaps = new Set<string>(), seenBatches = new Set<string>()
  let estimated = 0
  for (const [sequence, batch] of plan.batches.entries()) {
    const spec = reservation.batches[sequence], proof = r.calls[sequence], lineage = r.provenance[sequence]
    const { claim, reply, audit } = proof
    const { batch_digest, ...batchBody } = batch
    requireValue(!seenBatches.has(batch_digest) && generationDigest(batch_digest) && await canonicalDigest(batchBody) === batch_digest
      && batch.sequence === sequence && batch.generation_input_digest === r.request.input_digest
      && generationEqual(batch.context_pin, r.context_pin) && generationEqual(batch.scope_pin, r.scope_pin)
      && keys(spec, ['sequence', 'batch_digest', 'messages_hash', 'estimated_input_tokens']) && spec.sequence === sequence && spec.batch_digest === batch_digest
      && generationDigest(spec.messages_hash) && integer(spec.estimated_input_tokens, 1, Math.min(limits.max_input_tokens_per_call, p.context_tokens - limits.max_output_tokens_per_call))
      && ids(batch.mandatory_constraint_ids) && generationEqual([...batch.mandatory_constraint_ids].sort(),
        r.proposal.coverage.rows.filter((row) => ['acceptance_criterion', 'business_rule'].includes(row.kind)).flatMap((row) => row.constraint_ids).sort())
      && ids(batch.global_rule_ids) && Array.isArray(batch.obligations) && batch.obligations.length > 0)
    seenBatches.add(batch_digest); estimated += spec.estimated_input_tokens
    const batchRows = new Set<string>()
    for (const row of batch.obligations) {
      const expected = rows.get(row.row_id)
      requireValue(expected && !ownedRows.has(row.row_id) && row.oracle_digest === expected.oracle_digest
        && generationEqual(row.constraint_ids, expected.constraint_ids) && await canonicalDigest(row.oracle) === row.oracle_digest)
      ownedRows.add(row.row_id); batchRows.add(row.row_id)
    }
    requireValue(keys(proof, ['claim', 'reply', 'audit'])
      && keys(claim, ['project_id', 'invocation_id', 'sequence', 'batch_digest', 'call_id', 'request_hash', 'reserved_at'])
      && keys(reply, ['project_id', 'invocation_id', 'sequence', 'batch_digest', 'call_id', 'response_hash', 'usage', 'artifact_hash'])
      && keys(audit, ['id', 'provider', 'model_name', 'request_hash', 'response_hash', 'input_tokens', 'output_tokens', 'usage_source', 'occurred_at'])
      && [claim, reply].every((item) => item.project_id === r.project_id && item.invocation_id === r.invocation_id
        && item.sequence === sequence && item.batch_digest === batch_digest && item.call_id === m.call_ids[sequence])
      && audit.id === claim.call_id && audit.provider === p.provider && audit.model_name === p.model_name
      && audit.request_hash === claim.request_hash && audit.response_hash === reply.response_hash
      && [claim.request_hash, reply.response_hash, reply.artifact_hash].every(generationDigest)
      && timestamp(claim.reserved_at) && timestamp(audit.occurred_at) && audit.usage_source === 'provider'
      && keys(reply.usage, ['input_tokens', 'output_tokens', 'cost_nanos_at_policy_rates', 'currency', 'usage_source', 'invoice_verified'])
      && reply.usage.usage_source === 'provider' && reply.usage.invoice_verified === false && reply.usage.currency === p.currency
      && integer(reply.usage.input_tokens, 1, Math.min(limits.max_input_tokens_per_call, p.context_tokens - limits.max_output_tokens_per_call))
      && integer(reply.usage.output_tokens, 1, limits.max_output_tokens_per_call)
      && audit.input_tokens === reply.usage.input_tokens && audit.output_tokens === reply.usage.output_tokens
      && reply.usage.cost_nanos_at_policy_rates === reply.usage.input_tokens * p.input_nanos_per_token + reply.usage.output_tokens * p.output_nanos_per_token)
    requireValue(await canonicalDigest({ schema: 'nasus.test-design-batch-call.v1', request: r.request, plan_digest,
      sequence, batch_digest, messages_hash: spec.messages_hash }) === claim.request_hash
      && keys(lineage, ['batch_digest', 'response_hash', 'case_id_map', 'gap_id_map']) && lineage.batch_digest === batch_digest && lineage.response_hash === reply.response_hash)
    for (const [mapping, items, seen, prefix] of [[lineage.case_id_map, cases, seenCases, 'case_'], [lineage.gap_id_map, gaps, seenGaps, 'gap_']] as const) {
      requireValue(mapping && typeof mapping === 'object' && !Array.isArray(mapping) && ids(Object.keys(mapping)) && ids(Object.values(mapping)))
      for (const [local, stable] of Object.entries(mapping)) {
        const item = items.get(stable)
        requireValue(item && !seen.has(stable) && stable === prefix + (await canonicalDigest([r.request.input_digest, batch_digest, local])).slice(7))
        if ('assertions' in item) requireValue(item.assertions.every((a) => batchRows.has(a.row_id))
          && generationEqual([...item.global_constraint_ids].sort(), [...batch.global_rule_ids].sort())
          && await Promise.all(item.assertions.map(async (a) => a.oracle_digest === await canonicalDigest(a.oracle))).then((checks) => checks.every(Boolean)))
        else requireValue(item.row_ids.every((id) => batchRows.has(id)))
        seen.add(stable)
      }
    }
  }
  requireValue(estimated === b.estimated_input_tokens && ownedRows.size === rows.size && seenCases.size === cases.size && seenGaps.size === gaps.size
    && await canonicalDigest({ input_digest: r.request.input_digest, cases: r.proposal.cases, gaps: r.proposal.gaps }) === r.merged_output_hash)
  if (recovered) await verifyBatchRecoveryPins(v)
}

export async function verifyGenerationArchiveView(value: unknown, scope: ScopeArchive,
  job: Pick<GenerationJob, 'project_id' | 'generation_id' | 'source_invocation_id' | 'invocation_id'>): Promise<GenerationArchive> {
  const v = verifyGenerationArchive(value, scope, job)
  if (['nasus.test-design-result.v3', 'nasus.test-design-result.v4'].includes(v.result.schema)) await verifyBatchProvenance(v as GenerationBatchArchive)
  return v
}
