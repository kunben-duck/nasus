import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { exactKeys, identity, originalObservationIdentity, utc } from './environmentRecordValidation'
import { fixtureRecipeRequest } from './httpFixtureRecipeValidation'
import { requireRunPlan } from './runPlanValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { FixtureRecipeView } from './types/httpFixtureRecipes'
import type { EnvironmentRecordView } from './types/environmentRecords'
import type { FixtureCommandAttempt, FixtureCommandStage, FixtureGrantRequest, FixtureGrantScope, FixtureGrantView, FixtureJobView, FixtureOperation } from './types/httpFixtureOperations'

export const fixtureTools = { grant: 'quality.http_fixture.authorize', execute: 'quality.http_fixture.execute', cancel: 'quality.http_fixture.cancel' } as const
export const fixtureFalseAuthorities = ['execution_authorized', 'canonical_execution_committed', 'business_coverage_verified', 'baseline_restored'] as const
const coordinatorKeys = new Set(['idempotency_key', 'agent_goal_id', 'agent_step_id', 'agent_plan_step_id', 'requested_tool_id', 'user_message',
  'planner_kind', 'stream_reply', 'version_id', 'us_id', 'task_id', 'conversation_id', 'agent_loop_iteration_id', 'agent_loop_attempt',
  'goal_template', 'goal_description', 'tool_plan_index', 'tool_plan_reason', 'confirmed_actor_id', 'fixture_claim_protocol', 'confirmed_by_user', 'confirmed_at'])
export function requireFixtureOperationInput(stage: FixtureCommandStage, input: Record<string, unknown>) {
  const fields = stage === 'grant' ? ['project_id', 'recipe_id', 'recipe_artifact_hash', 'attempt_id', 'operation', 'timeout_ms',
    'policy_revision', 'environment_record_id', 'environment_record_artifact_hash'] : stage === 'execute'
    ? ['project_id', 'grant_id', 'grant_digest', 'operation'] : ['project_id', 'invocation_id']
  exactKeys(input, fields)
  requireRunPlan(identity(input.project_id))
  if (stage === 'grant') requireRunPlan([input.recipe_id, input.attempt_id, input.environment_record_id].every(identity)
    && [input.recipe_artifact_hash, input.environment_record_artifact_hash].every(generationDigest)
    && input.policy_revision === 'nasus.http-fixture-grant.v2' && Number.isInteger(input.timeout_ms)
    && typeof input.timeout_ms === 'number' && input.timeout_ms >= 1000 && input.timeout_ms <= 120000)
  if (stage === 'execute') requireRunPlan(identity(input.grant_id) && generationDigest(input.grant_digest))
  if (stage !== 'cancel') requireRunPlan(['setup', 'cleanup'].includes(input.operation as string))
  else requireRunPlan(identity(input.invocation_id))
}
export function fixtureBusinessInput(command: ToolInvocation): Record<string, unknown> {
  requireRunPlan(command?.input_payload && typeof command.input_payload === 'object' && !Array.isArray(command.input_payload))
  return Object.fromEntries(Object.entries(command.input_payload).filter(([key]) => !coordinatorKeys.has(key)))
}
export async function requireFixtureOperationCommand(command: ToolInvocation, stage: FixtureCommandStage, attempt: FixtureCommandAttempt,
  input: Record<string, unknown>, actorId: string) {
  requireFixtureOperationInput(stage, input)
  requireRunPlan(new TextEncoder().encode(JSON.stringify(command)).length <= 128 * 1024
    && identity(actorId) && identity(attempt.requestKey) && generationDigest(attempt.requestHash)
    && identity(command?.id) && (!attempt.commandId || attempt.commandId === command.id) && command.tool_id === fixtureTools[stage]
    && command.input_payload.idempotency_key === attempt.requestKey && generationEqual(fixtureBusinessInput(command), input)
    && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'waiting_confirmation', 'running', 'completed', 'failed', 'cancelled'].includes(command.status))
  if (['running', 'completed'].includes(command.status)) requireRunPlan(command.input_payload.confirmed_by_user === true
    && command.input_payload.confirmed_actor_id === actorId && utc(command.input_payload.confirmed_at))
  if (command.result) requireRunPlan(command.result.invocation_id === command.id && command.result.status === command.status)
  return command
}
export async function fixtureGrantRequest(plan: RunPlanArchive, recipe: FixtureRecipeView, environment: EnvironmentRecordView,
  fields: { attemptId: string; operation: FixtureOperation; timeoutMs: number }): Promise<FixtureGrantRequest> {
  const p = plan.metadata, r = recipe.metadata, e = environment.metadata, declaration = plan.artifact.plan.selection.environment
  requireRunPlan(generationEqual(recipe.archive.request, await fixtureRecipeRequest(plan, recipe.archive.request.manifest))
    && r.project_id === p.project_id && r.run_plan_id === p.run_plan_id && r.run_plan_artifact_hash === p.artifact_hash
    && e.project_id === p.project_id && e.run_plan_id === p.run_plan_id && e.run_plan_artifact_hash === p.artifact_hash
    && e.plan_digest === p.plan_digest && e.image_revision_id === p.image_revision_id && e.manifest_id === p.manifest_id
    && e.target_artifact_hash === plan.artifact.plan.selection.target_build.artifact_hash
    && e.environment_id === declaration.environment_id && e.operator_policy_digest === declaration.inventory_hash
    && declaration.kind === 'local' && declaration.base_url === 'http://127.0.0.1:8080'
    && environment.archive.observation.inventory.namespace_origin === declaration.base_url
    && identity(fields.attemptId) && ['setup', 'cleanup'].includes(fields.operation)
    && Number.isInteger(fields.timeoutMs) && fields.timeoutMs >= 1000 && fields.timeoutMs <= 120000)
  return { project_id: p.project_id, recipe_id: r.record_id, recipe_artifact_hash: r.artifact_hash,
    attempt_id: fields.attemptId, operation: fields.operation, timeout_ms: fields.timeoutMs, policy_revision: 'nasus.http-fixture-grant.v2',
    environment_record_id: e.record_id, environment_record_artifact_hash: e.artifact_hash }
}
export async function verifyFixtureGrant(value: unknown, input: FixtureGrantRequest, plan: RunPlanArchive, recipe: FixtureRecipeView,
  environment: EnvironmentRecordView, commandId: string, actorId: string): Promise<FixtureGrantView> {
  const v = value as FixtureGrantView, m = v?.metadata
  exactKeys(v, ['metadata', 'historical_not_live'])
  requireRunPlan(v.historical_not_live === true)
  const native = { record_id: environment.metadata.record_id, artifact_hash: environment.metadata.artifact_hash,
    inventory_hash: environment.metadata.inventory_hash, operator_policy_digest: environment.metadata.operator_policy_digest }
  const scope: FixtureGrantScope = { project_id: input.project_id, attempt_id: input.attempt_id, case_id: recipe.metadata.case_id,
    parent_digest: plan.metadata.plan_digest, data_manifest_hash: recipe.metadata.data_manifest_hash,
    environment_id: environment.metadata.environment_id, artifact_hash: environment.metadata.target_artifact_hash,
    inventory_hash: native.inventory_hash, timeout_ms: input.timeout_ms }
  requireRunPlan(m && utc(m.recorded_at) && utc(m.expires_at) && Date.parse(m.expires_at) - Date.parse(m.recorded_at) === 900000
    && identity(actorId) && generationDigest(m.source_scope_digest)
    && generationEqual(input, await fixtureGrantRequest(plan, recipe, environment,
      { attemptId: input.attempt_id, operation: input.operation, timeoutMs: input.timeout_ms })))
  const payload = { schema: input.policy_revision, project_id: input.project_id,
    record_id: await originalObservationIdentity(commandId, 'nasus:http-fixture-grant:'), invocation_id: commandId,
    actor_id: actorId, recorded_at: m.recorded_at, expires_at: m.expires_at, request: input, scope,
    source_scope_digest: m.source_scope_digest, native_environment: native }
  const expected = { ...input, schema: payload.schema, record_id: payload.record_id, invocation_id: commandId,
    actor_id: actorId, recorded_at: m.recorded_at, expires_at: m.expires_at, scope, source_scope_digest: m.source_scope_digest,
    native_environment: native, request_hash: await canonicalDigest(input), scope_digest: await canonicalDigest(scope),
    grant_digest: await canonicalDigest(payload), status: 'issued', historical_not_live: true, scope_permission_recorded: true,
    ...Object.fromEntries(fixtureFalseAuthorities.map((key) => [key, false])), fixtures_verified: false,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
  requireRunPlan(generationEqual(m, expected)); return v
}
export async function verifyFixtureJob(value: unknown, command: ToolInvocation, grant: FixtureGrantView, recipe: FixtureRecipeView): Promise<FixtureJobView> {
  const v = value as FixtureJobView, m = grant.metadata
  const selection = { project_id: m.project_id, grant_id: m.record_id, grant_digest: m.grant_digest, operation: m.operation }
  const base = ['schema', 'project_id', 'invocation_id', 'request_digest', 'selection', 'status', 'intent_digest', 'phases',
    'cancellation_requested', 'cancellation_delivered', ...fixtureFalseAuthorities]
  exactKeys(v, v?.schema === 'nasus.http-fixture-job.v2' ? [...base, 'preparation_digest', 'phase', 'target_observation_verified'] : base)
  requireRunPlan(['nasus.http-fixture-job.v1', 'nasus.http-fixture-job.v2'].includes(v.schema)
    && v.project_id === m.project_id && v.invocation_id === command.id && generationEqual(v.selection, selection)
    && generationEqual(fixtureBusinessInput(command), selection) && ['running', 'completed', 'failed', 'cancelled'].includes(command.status)
    && command.input_payload.confirmed_by_user === true && command.input_payload.confirmed_actor_id === m.actor_id
    && utc(command.input_payload.confirmed_at) && v.status === command.status
    && v.request_digest === await canonicalDigest({ tool_id: command.tool_id, input_payload: command.input_payload })
    && command.tool_id === fixtureTools.execute && fixtureFalseAuthorities.every((key) => v[key] === false)
    && typeof v.cancellation_requested === 'boolean' && typeof v.cancellation_delivered === 'boolean'
    && (!v.cancellation_delivered || v.cancellation_requested) && (v.status !== 'cancelled' || v.cancellation_requested)
    && (!v.cancellation_requested || v.status === 'cancelled') && Array.isArray(v.phases))
  if (v.schema === 'nasus.http-fixture-job.v2') {
    requireRunPlan(generationDigest(v.preparation_digest) && v.intent_digest === null && !v.phases.length && v.target_observation_verified === false
      && v.status !== 'completed' && v.phase === ({ running: 'preparing', failed: 'preparation_failed', cancelled: 'preparation_cancelled' } as const)[v.status as 'running' | 'failed' | 'cancelled'])
  } else {
    const expected = m.operation === 'setup' ? ['setup'] : recipe.archive.request.manifest.setup_steps
      .filter((step) => step.action === 'capture_json').map((step) => 'cleanup:' + step.binding_id)
    requireRunPlan(generationDigest(v.intent_digest) && generationEqual(v.phases.map((item) => item.phase), expected)
      && new Set(v.phases.map((item) => item.claim_id)).size === expected.length)
    for (const item of v.phases) {
      exactKeys(item, ['phase', 'claim_id', 'state', ...(item.state === 'not_dispatched' ? [] : ['dispatch_digest']),
        ...(item.state === 'observed' ? ['result_status', 'result_digest'] : [])])
      requireRunPlan(item.claim_id === 'fixture_' + (await canonicalDigest([m.project_id, m.attempt_id, m.scope.case_id, item.phase])).slice(7)
        && ['not_dispatched', 'outcome_unknown', 'observed'].includes(item.state)
        && (item.state === 'not_dispatched' || generationDigest(item.dispatch_digest))
        && (item.state !== 'observed' || generationDigest(item.result_digest) && ['passed', 'failed', 'error', 'timed_out'].includes(item.result_status)))
    }
    requireRunPlan(v.status !== 'completed' || v.phases.length > 0 && v.phases.every((item) => item.state === 'observed'))
  }
  return v
}
