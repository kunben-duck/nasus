import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { exactKeys, identity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import { fixtureFalseAuthorities } from './httpFixtureOperationValidation'
import { verifyFixtureHistoryItem } from './httpFixtureHistoryValidation'
import type { FixtureHistoryItem } from './types/httpFixtureHistory'
import type { FixtureOriginalObservation } from './types/httpFixtureObservations'

export async function verifyFixtureOriginalObservation(value: unknown, item: FixtureHistoryItem, sourceScopeDigest: string): Promise<FixtureOriginalObservation> {
  verifyFixtureHistoryItem(item, item.project_id)
  const v = value as FixtureOriginalObservation
  exactKeys(v, ['schema', 'selected', 'execution', 'expected_phases', 'job', 'state', 'source_scope_digest', 'observation', ...fixtureFalseAuthorities])
  requireRunPlan(v.schema === 'nasus.http-fixture-original-observation.v1' && generationEqual(v.selected, item)
    && generationDigest(sourceScopeDigest) && v.source_scope_digest === sourceScopeDigest
    && v.observation === 'original_persisted_journal_not_live_target' && fixtureFalseAuthorities.every((key) => v[key] === false)
    && Array.isArray(v.expected_phases) && v.expected_phases.length <= 16)
  if (item.stage === 'grant') {
    requireRunPlan(v.execution === null && v.job === null && !v.expected_phases.length && v.state === 'not_execution')
    return v
  }
  const e = verifyFixtureHistoryItem(v.execution, item.project_id)
  requireRunPlan(e.stage === 'execute' && e.invocation_id === item.original_execution_id
    && (item.stage !== 'execute' || generationEqual(e, item))
    && ['project_id', 'recipe_id', 'recipe_artifact_hash', 'run_plan_id', 'run_plan_artifact_hash', 'case_id', 'attempt_id', 'operation', 'grant_id', 'grant_digest']
      .every((key) => e[key as keyof FixtureHistoryItem] === item[key as keyof FixtureHistoryItem]))
  if (['pending', 'waiting_confirmation', 'waiting_approval'].includes(e.status)) {
    requireRunPlan(v.job === null && !v.expected_phases.length && v.state === 'not_confirmed'); return v
  }
  requireRunPlan(v.expected_phases.length > 0
    && new Set(v.expected_phases.map((pin) => pin.phase)).size === v.expected_phases.length)
  for (const pin of v.expected_phases) {
    exactKeys(pin, ['phase', 'claim_id'])
    requireRunPlan(typeof pin.phase === 'string' && pin.phase.length <= 136 && (e.operation === 'setup'
      ? v.expected_phases.length === 1 && pin.phase === 'setup'
      : pin.phase.startsWith('cleanup:') && identity(pin.phase.slice(8)))
      && pin.claim_id === 'fixture_' + (await canonicalDigest([e.project_id, e.attempt_id, e.case_id, pin.phase])).slice(7))
  }
  const job = v.job
  requireRunPlan(job && ['nasus.http-fixture-job.v1', 'nasus.http-fixture-job.v2'].includes(job.schema))
  const base = ['schema', 'project_id', 'invocation_id', 'request_digest', 'selection', 'status', 'intent_digest', 'phases',
    'cancellation_requested', 'cancellation_delivered', ...fixtureFalseAuthorities]
  exactKeys(job, job.schema === 'nasus.http-fixture-job.v2' ? [...base, 'preparation_digest', 'phase', 'target_observation_verified'] : base)
  requireRunPlan(job.project_id === e.project_id && job.invocation_id === e.invocation_id && job.request_digest === e.request_digest
    && job.status === e.status && ['running', 'completed', 'failed', 'cancelled'].includes(job.status)
    && generationEqual(job.selection, { project_id: e.project_id, grant_id: e.grant_id, grant_digest: e.grant_digest, operation: e.operation })
    && fixtureFalseAuthorities.every((key) => job[key] === false) && Array.isArray(job.phases)
    && typeof job.cancellation_requested === 'boolean' && typeof job.cancellation_delivered === 'boolean'
    && (!job.cancellation_delivered || job.cancellation_requested) && job.cancellation_requested === (job.status === 'cancelled'))
  if (job.schema === 'nasus.http-fixture-job.v2') {
    const phase = { running: 'preparing', failed: 'preparation_failed', cancelled: 'preparation_cancelled' }
    requireRunPlan(generationDigest(job.preparation_digest) && job.intent_digest === null && job.phases.length === 0
      && job.target_observation_verified === false && job.status !== 'completed'
      && job.phase === phase[job.status as keyof typeof phase] && v.state === job.phase)
    return v
  }
  requireRunPlan(generationDigest(job.intent_digest) && job.phases.length === v.expected_phases.length)
  for (const [index, phase] of job.phases.entries()) {
    exactKeys(phase, ['phase', 'claim_id', 'state', ...(phase.state === 'not_dispatched' ? [] : ['dispatch_digest']),
      ...(phase.state === 'observed' ? ['result_status', 'result_digest'] : [])])
    requireRunPlan(phase.phase === v.expected_phases[index].phase && phase.claim_id === v.expected_phases[index].claim_id
      && ['not_dispatched', 'outcome_unknown', 'observed'].includes(phase.state)
      && (phase.state === 'not_dispatched' || generationDigest(phase.dispatch_digest))
      && (phase.state !== 'observed' || generationDigest(phase.result_digest) && ['passed', 'failed', 'error', 'timed_out'].includes(phase.result_status)))
  }
  const states = job.phases.map((phase) => phase.state)
  const state = states.includes('outcome_unknown') ? 'outcome_unknown' : states.every((s) => s === 'observed') ? 'observed'
    : states.includes('observed') ? 'partially_observed' : 'not_dispatched'
  requireRunPlan(v.state === state && (job.status !== 'completed' || state === 'observed')); return v
}
