import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { identity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import { locatorQuery } from './runPlanLocatorValidation'
import { verifyLocatorAttempt } from './runPlanLocatorRecordRecovery'
import { locatorRecordIdentity, verifyLocatorRecord } from './runPlanLocatorRecordValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { LocatorRecordAttempt, LocatorRecordRequest } from './types/runPlanLocatorRecords'

const tool = 'quality.run_plan.record_locators'
export async function requireLocatorCommand(value: ToolInvocation, attempt: LocatorRecordAttempt) {
  verifyLocatorAttempt(attempt)
  const body = value?.input_payload, input = { project_id: body?.project_id, run_plan_id: body?.run_plan_id,
    run_plan_artifact_hash: body?.run_plan_artifact_hash } as LocatorRecordRequest
  requireRunPlan(value && identity(value.id) && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === tool
    && body?.idempotency_key === attempt.requestKey && input.project_id === attempt.projectId && input.run_plan_id === attempt.planId
    && input.run_plan_artifact_hash === attempt.planHash && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
  if (value.status === 'completed') {
    const result = value.result
    requireRunPlan(body.confirmed_by_user === true && result?.status === 'completed' && result.invocation_id === value.id
      && generationEqual(result.object_refs, ['run_plan_locators:' + await locatorRecordIdentity(value.id)]))
  }
  return { command: value, input }
}
async function confirm(attempt: LocatorRecordAttempt) {
  requireRunPlan(attempt.commandId)
  return requireLocatorCommand(await platformApi.confirmToolInvocation(attempt.commandId), attempt)
}
export const locatorRecordApi = { confirm,
  async register(input: LocatorRecordRequest, attempt: LocatorRecordAttempt, acknowledge: (v: LocatorRecordAttempt) => void) {
    requireRunPlan(!attempt.commandId && await canonicalDigest(input) === attempt.requestHash)
    const pending = await requireLocatorCommand(await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt.requestKey, input: { ...input } }), attempt)
    requireRunPlan(pending.command.status === 'waiting_confirmation')
    const fixed = { ...attempt, commandId: pending.command.id }; acknowledge(fixed)
    return confirm(fixed)
  },
  async recover(attempt: LocatorRecordAttempt, plan: RunPlanArchive, signal: AbortSignal) {
    verifyLocatorAttempt(attempt); signal.throwIfAborted()
    const command = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId, tool_id: tool, request_key: attempt.requestKey })}`,
        { signal, cache: 'no-store' })
    const original = await requireLocatorCommand(command, attempt)
    requireRunPlan(generationEqual(original.input, locatorQuery(plan)))
    signal.throwIfAborted(); return original
  },
  async read(command: ToolInvocation, plan: RunPlanArchive, signal: AbortSignal) {
    requireRunPlan(command.status === 'completed' && command.result?.run_plan_locator_record)
    signal.throwIfAborted()
    const input = locatorQuery(plan)
    await requireLocatorCommand(command, { projectId: input.project_id, planId: input.run_plan_id, planHash: input.run_plan_artifact_hash,
      commandId: command.id, requestKey: command.input_payload?.idempotency_key as string, requestHash: await canonicalDigest(input) })
    signal.throwIfAborted()
    const id = await locatorRecordIdentity(command.id)
    const view = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/run-plan-locators/${encodeURIComponent(id)}`,
      { signal, cache: 'no-store' })
    const verified = await verifyLocatorRecord(view, plan, command.id, id)
    requireRunPlan(generationEqual(command.result?.run_plan_locator_record, { metadata: verified.metadata, historical_not_live: true }))
    signal.throwIfAborted(); return verified
  },
}
