import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scriptId, scriptProtocol } from './automationScriptValidation'
import type { ScriptArchive, ScriptReviewArchive } from './types/automationScripts'
import type { RunPlanArchive, RunPlanPreview, RunPlanRequest, RunPlanSelection, RunPlanSources, RunPlanValue } from './types/runPlans'

export const runPlanGates = ['native_build_source_attestation', 'native_environment_and_locator_verification',
  'fixture_setup_cleanup_verification', 'independent_execution_authorization', 'canonical_run_plan_execution']
export function requireRunPlan(value: unknown): asserts value { if (!value) throw new Error('Original RunPlan scope or archive cannot be verified') }
export const requestKeys = ['project_id', 'script_revision_id', 'script_artifact_hash', 'review_revision_id', 'review_artifact_hash',
  'target_build', 'environment', 'fixtures', 'reason', 'policy_revision', 'plan_digest', 'source_scope_digest'] as const
export function planSelection(request: RunPlanRequest): RunPlanSelection {
  return Object.fromEntries(Object.entries(request).filter(([key]) => key !== 'plan_digest' && key !== 'source_scope_digest')) as unknown as RunPlanSelection
}
export function runPlanPolicy(draft: ScriptArchive): RunPlanSelection['policy_revision'] {
  const protocol = scriptProtocol(draft.result.proposal)
  return protocol === 'nasus.runner-http-execution.v3' ? 'nasus.run-plan.v3' : protocol === 'nasus.runner-http-execution.v2' ? 'nasus.run-plan.v2' : 'nasus.run-plan.v1'
}
export function runPlanArtifactSchema(policy: RunPlanSelection['policy_revision']): RunPlanArchive['artifact']['schema'] {
  requireRunPlan(['nasus.run-plan.v1', 'nasus.run-plan.v2', 'nasus.run-plan.v3'].includes(policy))
  return policy === 'nasus.run-plan.v3' ? 'nasus.run-plan-artifact.v3' : policy === 'nasus.run-plan.v2' ? 'nasus.run-plan-artifact.v2' : 'nasus.run-plan-artifact.v1'
}
export async function expectedRunPlan(selection: RunPlanSelection, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources): Promise<RunPlanValue> {
  requireRunPlan(selection.project_id === draft.metadata.project_id && selection.script_revision_id === draft.metadata.script_revision_id
    && selection.script_artifact_hash === draft.metadata.artifact_hash && selection.review_revision_id === review.revision.revision_id
    && selection.review_artifact_hash === review.revision.artifact_hash && review.revision.status === 'reviewed'
    && review.assessment?.review_complete === true && !draft.result.proposal.gaps.length
    && review.revision.project_id === selection.project_id && review.revision.script_revision_id === selection.script_revision_id
    && review.revision.script_artifact_hash === selection.script_artifact_hash
    && sources.project_id === selection.project_id && sources.image_revision_id === draft.result.prepared.context_pin.image_revision_id
    && sources.image_artifact_hash === draft.result.prepared.context_pin.image_artifact_hash)
  const code = sources.source_members.filter((item) => item.source_type === 'code' && item.status === 'captured')
    .map(({ binding_id, source_revision_id }) => ({ binding_id, source_revision_id }))
  requireRunPlan(code.length && selection.target_build.code_sources.length === code.length && code.every((item) =>
    selection.target_build.code_sources.some((pin) => generationEqual(pin, item)))
    && new Set(selection.target_build.code_sources.map((item) => item.binding_id)).size === code.length)
  const cases = draft.result.prepared.cases
  requireRunPlan(selection.policy_revision === runPlanPolicy(draft))
  requireRunPlan(selection.fixtures.length === cases.length && new Set(selection.fixtures.map((item) => item.case_id)).size === cases.length)
  for (const item of cases) requireRunPlan(selection.fixtures.find((fixture) => fixture.case_id === item.case_id)?.preconditions_digest === await canonicalDigest(item.preconditions))
  const value = { schema: selection.policy_revision, project_id: selection.project_id, selection, source_pin: sources,
    script_pin: { script_revision_id: draft.metadata.script_revision_id, artifact_hash: draft.metadata.artifact_hash,
      proposal_hash: await canonicalDigest(draft.result.proposal), input_digest: draft.result.prepared.input_digest },
    review_pin: { revision_id: review.revision.revision_id, artifact_hash: review.revision.artifact_hash,
      request_hash: review.revision.request_hash, authority_actor: review.revision.authority_actor },
    prepared: draft.result.prepared, proposal: draft.result.proposal, status: 'prepared' as const,
    target_verification: 'declared_not_native_verified' as const, execution_authorized: false as const,
    automated_count: 0 as const, executed_on_target_count: 0 as const, passed_count: 0 as const, remaining_gates: runPlanGates }
  return { ...value, plan_digest: await canonicalDigest(value) }
}
export async function verifyRunPlanPreview(value: unknown, selection: RunPlanSelection, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources): Promise<RunPlanPreview> {
  const v = value as RunPlanPreview, plan = await expectedRunPlan(selection, draft, review, sources)
  requireRunPlan(v?.status === 'preview' && v.execution_authorized === false && v.target_verification === plan.target_verification
    && generationEqual(planSelection(v.request), selection) && generationDigest(v.request.source_scope_digest)
    && v.request.plan_digest === plan.plan_digest && v.case_count === plan.prepared.cases.length
    && v.obligation_count === plan.prepared.obligation_denominator && generationEqual(v.remaining_gates, ['fresh_prepare_confirmation', ...runPlanGates]))
  return v
}
export async function verifyRunPlanArchive(value: unknown, request: RunPlanRequest, commandId: string, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources): Promise<RunPlanArchive> {
  const v = value as RunPlanArchive, m = v?.metadata, a = v?.artifact, plan = await expectedRunPlan(planSelection(request), draft, review, sources)
  requireRunPlan(m && a && a.schema === runPlanArtifactSchema(plan.schema)
    && generationEqual(a.request, request) && generationEqual(a.plan, plan)
    && request.plan_digest === plan.plan_digest && m.project_id === request.project_id && m.invocation_id === commandId && scriptId(m.run_plan_id)
    && m.status === 'prepared' && m.execution_authorized === false && m.plan_digest === plan.plan_digest
    && m.context_id === draft.result.prepared.context_pin.context_id && m.image_revision_id === sources.image_revision_id && m.manifest_id === sources.manifest_id
    && m.script_revision_id === request.script_revision_id && m.review_revision_id === request.review_revision_id
    && ['project_id', 'run_plan_id', 'invocation_id', 'actor_id', 'recorded_at'].every((key) => generationEqual(a[key as keyof typeof a], m[key]))
    && scriptId(m.actor_id) && typeof m.recorded_at === 'string' && Number.isFinite(Date.parse(m.recorded_at))
    && await canonicalDigest(a) === m.artifact_hash && await canonicalDigest(request) === m.request_hash
    && v.historical_not_live === true && typeof v.current_use?.inputs_current === 'boolean'
    && (!v.current_use.inputs_current || draft.current_use.input_current) && v.current_use.target_verified === false && v.current_use.execution_authorized === false)
  return v
}
