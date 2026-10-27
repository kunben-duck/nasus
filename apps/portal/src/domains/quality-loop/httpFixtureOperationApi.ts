import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { identity, originalObservationIdentity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import { fixtureTools, requireFixtureOperationCommand, requireFixtureOperationInput, verifyFixtureGrant, verifyFixtureJob } from './httpFixtureOperationValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { FixtureRecipeView } from './types/httpFixtureRecipes'
import type { EnvironmentRecordView } from './types/environmentRecords'
import type { FixtureCommandAttempt, FixtureCommandStage, FixtureGrantRequest, FixtureGrantView } from './types/httpFixtureOperations'

export const fixtureOperationApi = {
  async submit(stage: FixtureCommandStage, attempt: FixtureCommandAttempt, input: Record<string, unknown>, actorId: string,
    acknowledge: (commandId: string) => void) {
    requireFixtureOperationInput(stage, input)
    requireRunPlan(!attempt.commandId && identity(actorId) && identity(attempt.requestKey) && attempt.requestHash === await canonicalDigest(input))
    const pending = await requireFixtureOperationCommand(await platformApi.invokeTool({ tool_id: fixtureTools[stage],
      idempotency_key: attempt.requestKey, input }), stage, attempt, input, actorId)
    requireRunPlan(pending.status === 'waiting_confirmation')
    acknowledge(pending.id)
    return this.confirm(stage, { ...attempt, commandId: pending.id }, input, actorId)
  },
  async confirm(stage: FixtureCommandStage, attempt: FixtureCommandAttempt, input: Record<string, unknown>, actorId: string) {
    requireFixtureOperationInput(stage, input)
    requireRunPlan(identity(attempt.commandId) && identity(actorId) && identity(attempt.requestKey) && attempt.requestHash === await canonicalDigest(input))
    const original = await requireFixtureOperationCommand(await platformApi.getToolInvocation(attempt.commandId), stage, attempt, input, actorId)
    requireRunPlan(original.status === 'waiting_confirmation')
    return requireFixtureOperationCommand(await platformApi.confirmToolInvocation(attempt.commandId), stage, attempt, input, actorId)
  },
  async recover(stage: FixtureCommandStage, attempt: FixtureCommandAttempt, input: Record<string, unknown>, actorId: string, signal: AbortSignal) {
    requireFixtureOperationInput(stage, input)
    requireRunPlan(identity(actorId) && identity(attempt.requestKey) && (!attempt.commandId || identity(attempt.commandId))
      && attempt.requestHash === await canonicalDigest(input)); signal.throwIfAborted()
    const value = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: input.project_id as string,
        tool_id: fixtureTools[stage], request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    const verified = await requireFixtureOperationCommand(value, stage, attempt, input, actorId)
    signal.throwIfAborted(); return verified
  },
  async readGrant(command: ToolInvocation, input: FixtureGrantRequest, plan: RunPlanArchive, recipe: FixtureRecipeView,
    environment: EnvironmentRecordView, actorId: string, signal: AbortSignal) {
    requireRunPlan(command.status === 'completed' && command.result?.http_fixture_grant)
    const id = await originalObservationIdentity(command.id, 'nasus:http-fixture-grant:'); signal.throwIfAborted()
    requireRunPlan(generationEqual(command.result.object_refs, ['http_fixture_grant:' + id]))
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/http-fixture-grants/${encodeURIComponent(id)}`,
      { signal, cache: 'no-store' })
    const grant = await verifyFixtureGrant(value, input, plan, recipe, environment, command.id, actorId)
    requireRunPlan(generationEqual(command.result.http_fixture_grant, grant)); signal.throwIfAborted(); return grant
  },
  async readJob(attempt: FixtureCommandAttempt, grant: FixtureGrantView, recipe: FixtureRecipeView, actorId: string, signal: AbortSignal) {
    const m = grant.metadata, input = { project_id: m.project_id, grant_id: m.record_id, grant_digest: m.grant_digest, operation: m.operation }
    // A terminal transition between the two GETs is not a corrupt receipt. Re-read the same ID only.
    for (let count = 0; count < 3; count++) {
      const command = await this.recover('execute', attempt, input, actorId, signal)
      if (['pending', 'waiting_confirmation'].includes(command.status)) return { command, job: undefined }
      signal.throwIfAborted()
      const raw = await request<unknown>(`/v1/projects/${encodeURIComponent(m.project_id)}/quality/http-fixture-executions/${encodeURIComponent(command.id)}`,
        { signal, cache: 'no-store' })
      if ((raw as { status?: unknown })?.status !== command.status && count < 2) continue
      const job = await verifyFixtureJob(raw, command, grant, recipe)
      signal.throwIfAborted(); return { command, job }
    }
    throw new Error('Original fixture status could not be verified')
  },
}
