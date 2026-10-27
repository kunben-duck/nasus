import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { exactKeys } from './environmentRecordValidation'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { caseId, caseJob, requireCaseParent } from './runPlanCaseValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { CaseExecutionHistory, CaseExecutionSelection } from './types/runPlanCaseJobs'

const statuses = ['passed', 'failed', 'error', 'timed_out']
export async function verifyCaseHistory(value: unknown, command: ToolInvocation, input: CaseExecutionSelection, plan: RunPlanArchive) {
  requireCaseParent(input, plan)
  const v = value as CaseExecutionHistory
  exactKeys(v, ['project_id', 'invocation_id', 'run_id', 'status', 'bound', 'history', 'historical_not_live', 'business_coverage_verified', 'canonical_execution_committed'])
  requireRunPlan(v.project_id === input.project_id && v.invocation_id === command.id && v.run_id === input.run_id
    && v.status === command.status && ['running', 'completed', 'failed', 'cancelled'].includes(v.status)
    && typeof v.bound === 'boolean' && v.historical_not_live === true && v.business_coverage_verified === false && v.canonical_execution_committed === false)
  if (!v.bound) { requireRunPlan(v.history === null && v.status !== 'completed'); return v }
  const h = v.history, p = plan.artifact.plan
  exactKeys(h, ['state', 'observations', 'historical_not_live'])
  requireRunPlan(h && h.historical_not_live === true && Array.isArray(h.observations))
  const s = h.state, bound = p.schema === 'nasus.run-plan.v3'
  exactKeys(s, ['schema', 'project_id', 'run_id', 'invocation_id', 'scope_digest', 'cases', 'state', 'cancelled', 'case_count',
    'observed_case_count', 'outcome_unknown_case_count', 'not_dispatched_case_count', 'business_coverage_verified', 'canonical_execution_committed',
    'automated_count', 'executed_on_target_count', 'passed_count', ...(bound ? ['fixture_scope_digest', 'fixture_input_pins'] : [])])
  requireRunPlan(s.schema === (bound ? 'nasus.run-plan-case-state.v2' : 'nasus.run-plan-case-state.v1')
    && s.project_id === v.project_id && s.run_id === v.run_id && s.invocation_id === v.invocation_id
    && generationDigest(s.scope_digest) && typeof s.cancelled === 'boolean' && s.cancelled === (v.status === 'cancelled')
    && Array.isArray(s.cases) && s.cases.length === p.prepared.cases.length && s.case_count === s.cases.length
    && s.business_coverage_verified === false && s.canonical_execution_committed === false
    && s.automated_count === 0 && s.executed_on_target_count === 0 && s.passed_count === 0)
  if (bound) {
    requireRunPlan(generationDigest(s.fixture_scope_digest) && Array.isArray(s.fixture_input_pins)
      && s.fixture_input_pins.length === s.cases.length)
    for (let i = 0; i < s.cases.length; i++) {
      const pin = s.fixture_input_pins![i]
      exactKeys(pin, ['case_id', 'capture_set_digest', 'fixture_input_digest'])
      requireRunPlan(pin.case_id === p.prepared.cases[i].case_id
        && generationDigest(pin.capture_set_digest) && generationDigest(pin.fixture_input_digest))
    }
  }
  async function jobFor(ordinal: number) {
    const job = await caseJob(plan, input, ordinal)
    return bound ? { ...job, metadata: { ...job.metadata,
      fixture_capture_digest: s.fixture_input_pins![ordinal].capture_set_digest, fixture_scope_digest: s.fixture_scope_digest! } } : job
  }
  for (let i = 0; i < s.cases.length; i++) {
    const row = s.cases[i], job = await jobFor(i)
    exactKeys(row, ['ordinal', 'case_id', 'case_digest', 'command_digest', 'claim_id', 'status', 'observation_digest'])
    requireRunPlan(row.ordinal === i && row.case_id === p.prepared.cases[i].case_id && row.case_digest === job.metadata.case_digest
      && row.command_digest === await canonicalDigest(bound ? { ...job, fixture_input_digest: s.fixture_input_pins![i].fixture_input_digest } : job)
      && row.claim_id === 'case_claim_' + (await canonicalDigest([input.project_id, input.run_id, row.case_id])).slice(7)
      && (statuses.includes(row.status) ? generationDigest(row.observation_digest) : ['outcome_unknown', 'not_dispatched'].includes(row.status) && row.observation_digest === null))
  }
  const observed = s.cases.filter((row) => statuses.includes(row.status)), unknown = s.cases.filter((row) => row.status === 'outcome_unknown')
  const pending = s.cases.filter((row) => row.status === 'not_dispatched')
  requireRunPlan([s.case_count, s.observed_case_count, s.outcome_unknown_case_count, s.not_dispatched_case_count].every(Number.isInteger)
    && s.observed_case_count === observed.length && s.outcome_unknown_case_count === unknown.length && s.not_dispatched_case_count === pending.length
    && h.observations.length === observed.length)
  const expected = unknown.length ? 'outcome_unknown' : observed.length === s.case_count ? 'observed'
    : s.cancelled ? 'cancelled' : observed.length ? 'partially_observed' : 'not_dispatched'
  requireRunPlan(s.state === expected && (v.status !== 'completed' || expected === 'observed'))
  for (let i = 0; i < observed.length; i++) {
    const row = observed[i], o = h.observations[i], job = await jobFor(row.ordinal), script = p.proposal.scripts.find((v) => v.case_id === row.case_id)!
    exactKeys(o, ['schema', 'project_id', 'plan_digest', 'run_id', 'timeout_ms', 'case_id', 'case_digest', 'context_pin', 'scope_pin',
      'generation_pin', 'mapping_pin', 'script_pin', 'review_pin', 'fixture_digest', 'status', 'actions', 'oracles', 'runner_receipt',
      'execution_authorized', 'business_coverage_verified', 'target_build_verified', 'automated_count', 'executed_on_target_count', 'passed_count', 'observation_digest',
      ...(bound ? ['fixture_input_digest', 'fixture_capture_digest'] : [])])
    const { observation_digest: digest, ...payload } = o
    requireRunPlan(o.schema === (bound ? 'nasus.run-plan-case-observation.v2' : 'nasus.run-plan-case-observation.v1')
      && o.project_id === v.project_id && o.plan_digest === input.plan_digest
      && o.run_id === input.run_id && o.timeout_ms === input.timeout_ms && o.case_id === row.case_id && o.case_digest === row.case_digest
      && o.status === row.status && digest === row.observation_digest && await canonicalDigest(payload) === digest
      && o.execution_authorized === false && o.business_coverage_verified === false && o.target_build_verified === false
      && o.automated_count === 0 && o.executed_on_target_count === 0 && o.passed_count === 0
      && o.fixture_digest === await canonicalDigest(p.selection.fixtures[row.ordinal]) && caseId(o.case_id))
    if (bound) {
      const pin = s.fixture_input_pins![row.ordinal], receipt = o.runner_receipt as Record<string, unknown>
      requireRunPlan(o.fixture_input_digest === pin.fixture_input_digest && o.fixture_capture_digest === pin.capture_set_digest
        && receipt && receipt.schema === 'nasus.runner-http-execution.v3'
        && receipt.fixture_input_hash === pin.fixture_input_digest && receipt.fixture_capture_digest === pin.capture_set_digest)
    }
    for (const key of ['context_pin', 'scope_pin', 'generation_pin', 'mapping_pin'] as const) requireRunPlan(generationEqual(o[key], p.prepared[key]))
    requireRunPlan(generationEqual(o.script_pin, p.script_pin) && generationEqual(o.review_pin, p.review_pin))
    const actions = o.actions as { action_index: number; action_digest: string; source_step_indices: number[]; status: string }[]
    const oracles = o.oracles as { row_id: string; action_index: number; source_step_index: number; oracle_digest: string; status: string }[]
    requireRunPlan(Array.isArray(actions) && actions.length === job.steps.length && Array.isArray(oracles) && oracles.length === script.assertions.length)
    for (let n = 0; n < actions.length; n++) {
      exactKeys(actions[n], ['action_index', 'action_digest', 'source_step_indices', 'status'])
      requireRunPlan(actions[n].action_index === n && actions[n].action_digest === await canonicalDigest(job.steps[n])
        && generationEqual(actions[n].source_step_indices, job.steps[n].source_step_indices) && ['passed', 'failed', 'error', 'skipped'].includes(actions[n].status))
    }
    for (let n = 0; n < oracles.length; n++) {
      exactKeys(oracles[n], ['row_id', 'action_index', 'source_step_index', 'oracle_digest', 'status'])
      const { status, ...assertion } = oracles[n]
      const original = script.assertions[n]
      requireRunPlan(generationEqual(assertion, { row_id: original.row_id, action_index: original.action_index,
        source_step_index: original.source_step_index, oracle_digest: original.oracle_digest }) && status === actions[assertion.action_index]?.status)
    }
  }
  return v
}
