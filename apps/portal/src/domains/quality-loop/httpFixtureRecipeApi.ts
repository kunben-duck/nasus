import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { identity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import { createLocatorRecovery, verifyLocatorAttempt } from './runPlanLocatorRecordRecovery'
import { fixtureRecipeIdentity, fixtureRecipeRequest, verifyFixtureRecipe } from './httpFixtureRecipeValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { FixtureRecipeAttempt, FixtureRecipeRequest } from './types/httpFixtureRecipes'

const tool = 'quality.http_fixture.register'
export const fixtureRecipeRecovery = createLocatorRecovery(() => window.sessionStorage, 'nasus.http-fixture-recipe.v1:')
export async function requireFixtureCommand(value: ToolInvocation, attempt: FixtureRecipeAttempt, plan: RunPlanArchive) {
  verifyLocatorAttempt(attempt)
  const body = value?.input_payload
  requireRunPlan(body)
  const input = await fixtureRecipeRequest(plan, body.manifest)
  requireRunPlan(value && identity(value.id) && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === tool
    && body.idempotency_key === attempt.requestKey && body.project_id === input.project_id && body.run_plan_id === input.run_plan_id
    && body.run_plan_artifact_hash === input.run_plan_artifact_hash && input.project_id === attempt.projectId && input.run_plan_id === attempt.planId
    && input.run_plan_artifact_hash === attempt.planHash && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
  if (value.status === 'completed') requireRunPlan(body.confirmed_by_user === true && value.result?.status === 'completed'
    && value.result.invocation_id === value.id && generationEqual(value.result.object_refs, ['http_fixture_recipe:' + await fixtureRecipeIdentity(value.id)]))
  return { command: value, input }
}
async function confirm(attempt: FixtureRecipeAttempt, plan: RunPlanArchive) {
  requireRunPlan(attempt.commandId)
  return requireFixtureCommand(await platformApi.confirmToolInvocation(attempt.commandId), attempt, plan)
}
export const fixtureRecipeApi = { confirm,
  async register(input: FixtureRecipeRequest, attempt: FixtureRecipeAttempt, plan: RunPlanArchive, acknowledge: (v: FixtureRecipeAttempt) => void) {
    requireRunPlan(!attempt.commandId && await canonicalDigest(input) === attempt.requestHash
      && generationEqual(input, await fixtureRecipeRequest(plan, input.manifest)))
    const pending = await requireFixtureCommand(await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt.requestKey, input: { ...input } }), attempt, plan)
    requireRunPlan(pending.command.status === 'waiting_confirmation')
    const fixed = { ...attempt, commandId: pending.command.id }; acknowledge(fixed)
    return confirm(fixed, plan)
  },
  async recover(attempt: FixtureRecipeAttempt, plan: RunPlanArchive, signal: AbortSignal) {
    verifyLocatorAttempt(attempt); signal.throwIfAborted()
    const command = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId, tool_id: tool, request_key: attempt.requestKey })}`,
        { signal, cache: 'no-store' })
    const original = await requireFixtureCommand(command, attempt, plan)
    signal.throwIfAborted(); return original
  },
  async read(command: ToolInvocation, plan: RunPlanArchive, signal: AbortSignal) {
    requireRunPlan(command.status === 'completed' && command.result?.http_fixture_recipe)
    signal.throwIfAborted()
    const attempt = { projectId: plan.metadata.project_id, planId: plan.metadata.run_plan_id, planHash: plan.metadata.artifact_hash,
      commandId: command.id, requestKey: command.input_payload.idempotency_key as string,
      requestHash: await canonicalDigest(await fixtureRecipeRequest(plan, command.input_payload.manifest)) }
    await requireFixtureCommand(command, attempt, plan); signal.throwIfAborted()
    const id = await fixtureRecipeIdentity(command.id)
    const view = await request<unknown>(`/v1/projects/${encodeURIComponent(attempt.projectId)}/quality/http-fixture-recipes/${encodeURIComponent(id)}`,
      { signal, cache: 'no-store' })
    const verified = await verifyFixtureRecipe(view, plan, command.id, id)
    requireRunPlan(generationEqual(command.result.http_fixture_recipe, { metadata: verified.metadata, historical_not_live: true }))
    signal.throwIfAborted(); return verified
  },
}
