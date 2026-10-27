import type { ScopeArchive } from './types/testDesignScope'
import type { GenerationArchive, GenerationHistoryPage, GenerationHistoryRequest, GenerationJob, GenerationPreview, GenerationSelection } from './types/testDesignGeneration'
import { oracleKeys } from './types/observableOracle'
import { verifyBatchRecoveryOffer } from './generationRecoveryValidation'

export const generationDigest = (value: unknown) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
export function generationEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false
  const x = Object.entries(a), y = Object.entries(b)
  return x.length === y.length && x.every(([key, value]) => Object.hasOwn(b, key) && generationEqual(value, (b as Record<string, unknown>)[key]))
}
function requireValue(valid: unknown): asserts valid { if (!valid) throw new Error('Fixed generation response could not be verified') }
const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max
const identity = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 128
const uniqueIds = (value: unknown): value is string[] => Array.isArray(value) && value.every(identity) && new Set(value).size === value.length

export function verifyGenerationHistory(value: unknown, request: GenerationHistoryRequest): GenerationHistoryPage {
  const v = value as GenerationHistoryPage
  requireValue(v && generationEqual(v.request, request) && identity(request.project_id) && identity(request.scope_revision_id)
    && generationDigest(request.scope_artifact_hash) && integer(request.limit, 1, 50)
    && typeof request.after_id === 'string' && request.after_id.length <= 128
    && Array.isArray(v.items) && v.items.length <= request.limit && typeof v.has_running === 'boolean'
    && v.generation_authorized === false && v.execution_authorized === false
    && Object.keys(v).length === 6 && uniqueIds(v.items.map((item) => item?.invocation_id)))
  for (const [index, item] of v.items.entries()) requireValue(Object.keys(item).length === 4 && identity(item.source_invocation_id)
    && ['quality.test_design.generate', 'quality.test_design.recover'].includes(item.tool_id)
    && ['running', 'completed', 'failed', 'cancelled'].includes(item.status)
    && (item.tool_id === 'quality.test_design.generate' ? item.source_invocation_id === item.invocation_id : item.source_invocation_id !== item.invocation_id)
    && item.invocation_id > (index === 0 ? request.after_id : v.items[index - 1].invocation_id)
    && (item.status !== 'running' || v.has_running))
  requireValue(v.next_after_id === null || identity(v.next_after_id) && v.items.length === request.limit && v.next_after_id === v.items.at(-1)?.invocation_id)
  return v
}

export function verifyGenerationPreview(value: unknown, selection: GenerationSelection, mode: 'single' | 'batch' = 'single'): GenerationPreview {
  const v = value as GenerationPreview, r = v?.request, p = v?.policy, b = v?.reservation, budget = selection.budget
  const count = mode === 'single' ? 1 : v?.call_count
  requireValue(r && p && b && Object.entries(selection).filter(([key]) => key !== 'budget').every(([key, item]) => generationEqual(item, r[key as keyof typeof r]))
    && generationEqual(budget, r.execution?.budget) && r.execution?.purpose === 'draft_test_design_source_egress'
    && [r.input_digest, r.model_config_digest, r.execution.plan_digest, r.execution.policy_digest, r.execution.source_scope_digest, p.tokenizer_digest].every(generationDigest)
    && Array.isArray(r.execution.source_binding_ids) && r.execution.source_binding_ids.length > 0
    && r.execution.source_binding_ids.every((id) => typeof id === 'string' && id.length > 0 && id.length <= 128)
    && generationEqual(r.execution.source_binding_ids, [...new Set(r.execution.source_binding_ids)].sort())
    && p.config_id === selection.model_config_id && p.currency === budget.currency && p.base_url === v.destination
    && [p.policy_id, p.revision, p.tokenizer_id, v.model_name].every((item) => typeof item === 'string' && item.length > 0 && item.length <= 256)
    && p.provider === v.provider && p.model_name === v.model_name && ['openai', 'openai_compatible', 'anthropic', 'gemini'].includes(v.provider)
    && ['tiktoken', 'huggingface_json'].includes(p.tokenizer_kind) && integer(p.context_tokens, 1024, 1000000)
    && integer(p.max_output_tokens, 512, 32768) && budget.max_output_tokens_per_call <= p.max_output_tokens
    && integer(p.input_nanos_per_token) && integer(p.output_nanos_per_token) && integer(p.framing_tokens, 1, 8192)
    && integer(count, 1, Math.min(64, budget.max_calls)) && b.currency === budget.currency && b.call_count === count && v.call_count === count && v.timeout_seconds === 120
    && v.batching === (mode === 'single' ? 'one_complete_input_no_truncation' : 'complete_constraint_batches_no_truncation')
    && integer(v.input_bytes, 1, count * 1024 * 1024)
    && b.count_basis === 'local_tokenizer_with_operator_framing' && b.cost_basis === 'operator_rate_ceiling_not_provider_invoice'
    && integer(b.estimated_input_tokens, count, count * Math.min(budget.max_input_tokens_per_call, p.context_tokens - budget.max_output_tokens_per_call))
    && b.reserved_input_tokens_per_call === p.context_tokens && b.max_output_tokens_per_call === budget.max_output_tokens_per_call
    && b.reserved_tokens === count * (p.context_tokens + budget.max_output_tokens_per_call) && b.reserved_tokens <= budget.max_reserved_tokens
    && integer(b.reserved_cost_nanos) && b.reserved_cost_nanos === count * (p.context_tokens * p.input_nanos_per_token + budget.max_output_tokens_per_call * p.output_nanos_per_token)
    && b.reserved_cost_nanos <= budget.max_reserved_cost_nanos && v.generation_authorized === false && v.execution_authorized === false)
  const url = new URL(v.destination)
  requireValue(url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash)
  return v
}

export function verifyGenerationJob(value: unknown, scope: ScopeArchive, id: string): GenerationJob {
  const v = value as GenerationJob
  requireValue(v && v.project_id === scope.revision.project_id && v.scope_revision_id === scope.revision.revision_id && v.invocation_id === id
    && ['running', 'completed', 'failed', 'cancelled'].includes(v.status) && typeof v.source_invocation_id === 'string' && !!v.source_invocation_id
    && [v.call_reserved, v.reply_archived, v.provider_outcome_unknown].every((item) => typeof item === 'boolean') && v.execution_authorized === false
    && (!v.reply_archived || v.call_reserved)
    && (v.generation_id === null || typeof v.generation_id === 'string' && v.generation_id.length > 0)
    && (v.status !== 'completed' || v.generation_id !== null))
  if (v.batch_progress) {
    const b = v.batch_progress, reservation = b.reservation
    requireValue(b.schema === 'nasus.test-design-batch-progress.v1' && generationDigest(b.plan_digest)
      && Object.keys(b).length === 14 && integer(b.call_count, 1, 64) && integer(b.claimed_calls, 0, b.call_count)
      && integer(b.archived_calls, 0, b.claimed_calls) && b.unknown_calls === b.claimed_calls - b.archived_calls
      && integer(b.unknown_calls, 0, 1) && b.unstarted_calls === b.call_count - b.claimed_calls
      && [b.known_input_tokens, b.known_output_tokens, b.known_cost_nanos_at_policy_rates].every((n) => integer(n))
      && b.reservation_released === false && b.invoice_verified === false && b.execution_authorized === false
      && v.call_reserved === (b.claimed_calls > 0) && v.reply_archived === (b.archived_calls === b.call_count)
      && v.provider_outcome_unknown === (b.unknown_calls > 0)
      && reservation?.call_count === b.call_count && reservation.count_basis === 'local_tokenizer_with_operator_framing'
      && Object.keys(reservation).length === 9 && ['USD', 'CNY'].includes(reservation.currency)
      && integer(reservation.reserved_input_tokens_per_call, 1, 1e6) && integer(reservation.max_output_tokens_per_call, 512, 32768)
      && integer(reservation.estimated_input_tokens, 1, b.call_count * reservation.reserved_input_tokens_per_call)
      && reservation.reserved_tokens === b.call_count * (reservation.reserved_input_tokens_per_call + reservation.max_output_tokens_per_call)
      && reservation.cost_basis === 'operator_rate_ceiling_not_provider_invoice'
      && integer(reservation.reserved_tokens, 1, 64e6) && integer(reservation.reserved_cost_nanos, 0, 9e15)
      && b.known_input_tokens + b.known_output_tokens <= reservation.reserved_tokens
      && b.known_input_tokens <= b.archived_calls * reservation.reserved_input_tokens_per_call
      && b.known_output_tokens <= b.archived_calls * reservation.max_output_tokens_per_call
      && (b.archived_calls > 0 || b.known_input_tokens + b.known_output_tokens + b.known_cost_nanos_at_policy_rates === 0)
      && b.known_cost_nanos_at_policy_rates <= reservation.reserved_cost_nanos
      && (v.status !== 'completed' || v.reply_archived))
  } else requireValue(v.provider_outcome_unknown === (v.call_reserved && !v.reply_archived))
  if (v.recovery_request !== null) {
    const r = v.recovery_request
    requireValue(r && v.status === 'failed' && v.reply_archived && !v.generation_id && id === v.source_invocation_id
      && r.project_id === v.project_id && r.invocation_id === id)
    if (v.batch_progress) verifyBatchRecoveryOffer(r, v.project_id, id, v.batch_progress)
    else requireValue(!('schema_version' in r) && Object.keys(r).length === 5
      && [r.request_hash, r.reply_artifact_hash, r.response_hash].every(generationDigest))
  }
  return v
}

export function verifyGenerationArchive(value: unknown, scope: ScopeArchive,
  job: Pick<GenerationJob, 'project_id' | 'generation_id' | 'source_invocation_id' | 'invocation_id'>): GenerationArchive {
  const v = value as GenerationArchive, m = v?.metadata, r = v?.result, c = r?.proposal?.coverage
  const contract = scope.request.contract, constraints = scope.assessment?.constraint_ids ?? []
  const expectedObligations = constraints.length + (contract ? ['risks', 'permissions', 'transitions', 'invariants'].reduce((total, key) =>
    total + contract[key as 'risks'].items.length, 0) + contract.examples.reduce((total, item) => total + 1 + (item.negative ? 1 : 0), 0) : 0)
  requireValue(m && r && c && m.project_id === job.project_id && m.generation_id === job.generation_id && m.scope_revision_id === scope.revision.revision_id
    && m.invocation_id === job.source_invocation_id && r.invocation_id === m.invocation_id && r.project_id === m.project_id && r.generation_id === m.generation_id
    && generationDigest(m.artifact_hash) && m.status === 'draft' && r.status === 'draft' && r.mapping_status === 'pending_independent_review'
    && r.execution_authorized === false && v.historical_not_live === true && v.current_use?.mapping_approved === false && v.current_use.execution_authorized === false
    && typeof v.current_use.scope_current === 'boolean' && r.request.project_id === m.project_id && r.request.scope_revision_id === scope.revision.revision_id
    && r.request.scope_artifact_hash === scope.revision.artifact_hash && generationDigest(r.request.input_digest)
    && generationEqual(r.context_pin, scope.context_pin) && r.scope_pin.revision_id === scope.revision.revision_id
    && r.scope_pin.artifact_hash === scope.revision.artifact_hash && r.scope_pin.request_hash === scope.revision.request_hash
    && ['nasus.test-design-result.v1', 'nasus.test-design-result.v2', 'nasus.test-design-result.v3', 'nasus.test-design-result.v4'].includes(r.schema)
    && (['nasus.test-design-result.v2', 'nasus.test-design-result.v4'].includes(r.schema)
      ? identity(m.recovery_invocation_id) && m.recovery_invocation_id === r.recovery_invocation_id && m.recovery_invocation_id !== m.invocation_id
      : !m.recovery_invocation_id && !r.recovery_invocation_id)
    && (job.invocation_id === job.source_invocation_id || r.recovery_invocation_id === job.invocation_id)
    && Array.isArray(r.proposal.cases) && Array.isArray(r.proposal.gaps) && m.case_count === r.proposal.cases.length && m.gap_count === r.proposal.gaps.length
    && c.schema === 'nasus.test-design-coverage.v1' && c.input_digest === r.request.input_digest && c.execution_authorized === false
    && generationEqual(c.context_pin, r.context_pin) && generationEqual(c.scope_pin, r.scope_pin)
    && [c.assertion_mapped_count, c.automated_count, c.executed_on_target_count, c.passed_count].every((count) => count === 0)
    && Array.isArray(c.rows) && c.obligation_denominator === c.rows.length && c.rows.length === expectedObligations && c.unknown_count === c.rows.length
    && c.constraint_denominator === constraints.length && c.planned_obligation_count === c.rows.filter((row) => row.planned).length
    && c.gap_obligation_count === c.rows.filter((row) => row.gap_ids?.length).length
    && c.planned_constraint_count === c.rows.filter((row) => ['acceptance_criterion', 'business_rule'].includes(row.kind) && row.planned).length
    && uniqueIds(c.rows.map((row) => row.row_id)) && uniqueIds(r.proposal.cases.map((item) => item.case_id))
    && uniqueIds(r.proposal.gaps.map((item) => item.gap_id)))
  const cases = new Map(r.proposal.cases.map((item) => [item.case_id, item]))
  const gaps = new Map(r.proposal.gaps.map((item) => [item.gap_id, item]))
  const rows = new Map(c.rows.map((row) => [row.row_id, row]))
  const constraintIds = new Set(constraints)
  const constraintRows = c.rows.filter((row) => ['acceptance_criterion', 'business_rule'].includes(row.kind))
  requireValue(constraintRows.length === constraints.length && constraintRows.every((row) => row.constraint_ids?.length === 1)
    && generationEqual(constraintRows.flatMap((row) => row.constraint_ids).sort(), [...constraints].sort()))
  for (const row of c.rows) requireValue(row.assertion_mapped === false && row.automated === false && row.executed_on_target === false && row.passed === false
    && row.unknown === true && row.mapping_status === 'pending_independent_review' && generationDigest(row.oracle_digest)
    && ['acceptance_criterion', 'business_rule', 'risks', 'permissions', 'transitions', 'invariants', 'positive_example', 'negative_example'].includes(row.kind)
    && uniqueIds(row.constraint_ids) && row.constraint_ids.length > 0 && row.constraint_ids.every((id) => constraintIds.has(id))
    && uniqueIds(row.planned_case_ids) && uniqueIds(row.gap_ids) && row.planned === (row.planned_case_ids.length > 0)
    && (row.planned || row.gap_ids.length > 0)
    && row.planned_case_ids.every((id) => cases.has(id))
    && row.gap_ids.every((id) => gaps.has(id))
    && generationEqual(row.planned_case_ids, row.proposed_assertion_case_ids))
  for (const item of r.proposal.cases) requireValue(typeof item.title === 'string' && item.title.length > 0
    && [item.preconditions, item.inputs, item.steps].every((items) => Array.isArray(items) && items.length > 0 && items.every((text) => typeof text === 'string'))
    && Array.isArray(item.assertions) && item.assertions.length > 0 && uniqueIds(item.assertions.map((a) => a.row_id))
    && uniqueIds(item.global_constraint_ids) && uniqueIds(item.supporting_fact_ids) && uniqueIds(item.reused_case_ids)
    && item.assertions.every((a) => generationDigest(a.oracle_digest)
      && integer(a.step_index, 0, item.steps.length - 1) && rows.get(a.row_id)?.oracle_digest === a.oracle_digest && rows.get(a.row_id)?.planned_case_ids.includes(item.case_id)
      && a.oracle && Object.keys(a.oracle).length === 4 && oracleKeys.every((key) => typeof a.oracle[key] === 'string' && a.oracle[key].length > 0)))
  for (const gap of r.proposal.gaps) requireValue(typeof gap.description === 'string' && gap.description.length > 0
    && uniqueIds(gap.row_ids) && gap.row_ids.length > 0 && gap.row_ids.every((id) => rows.get(id)?.gap_ids.includes(gap.gap_id)))
  for (const row of c.rows) requireValue(row.planned_case_ids.every((id) => cases.get(id)?.assertions.some((a) => a.row_id === row.row_id))
    && row.gap_ids.every((id) => gaps.get(id)?.row_ids.includes(row.row_id)))
  return v
}
