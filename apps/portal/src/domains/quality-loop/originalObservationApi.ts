import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import { verifyEnvironmentAttempt } from './environmentRecordRecovery'
import { environmentRequest, environmentRequestKeys } from './environmentRecordValidation'
import type { ToolInvocation, ToolResult } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'
import type { EnvironmentRecordAttempt, EnvironmentRecordRequest } from './types/environmentRecords'

export function createOriginalObservationApi<T extends { metadata: unknown }>(definition: {
  tool: string; objectPrefix: string; receipt: keyof ToolResult; path: string
  identity: (command: string) => Promise<string>
  verify: (value: unknown, plan: RunPlanArchive, binding: RunPlanBuildArchive, command: string, record: string) => Promise<T>
}) {
  const requireCommand = async (value: ToolInvocation, attempt: EnvironmentRecordAttempt) => {
    verifyEnvironmentAttempt(attempt)
    const body = value?.input_payload, input = Object.fromEntries(environmentRequestKeys.map((key) => [key, body?.[key]])) as unknown as EnvironmentRecordRequest
    requireRunPlan(value && scriptId(value.id) && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === definition.tool
      && body?.idempotency_key === attempt.requestKey && input.project_id === attempt.projectId && input.run_plan_id === attempt.planId
      && input.run_plan_artifact_hash === attempt.planHash && input.build_binding_id === attempt.bindingId && input.build_binding_artifact_hash === attempt.bindingHash
      && await canonicalDigest(input) === attempt.requestHash && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
    if (value.status === 'completed') {
      const result = value.result, record = await definition.identity(value.id)
      requireRunPlan(body.confirmed_by_user === true && result?.status === 'completed' && result.invocation_id === value.id
        && Array.isArray(result.object_refs) && generationEqual(result.object_refs, [definition.objectPrefix + record]))
    }
    return { command: value, input }
  }
  const confirm = async (attempt: EnvironmentRecordAttempt) => {
    requireRunPlan(attempt.commandId)
    return requireCommand(await platformApi.confirmToolInvocation(attempt.commandId), attempt)
  }
  return { requireCommand, confirm,
    async register(input: EnvironmentRecordRequest, attempt: EnvironmentRecordAttempt, acknowledge: (value: EnvironmentRecordAttempt) => void) {
      requireRunPlan(!attempt.commandId && await canonicalDigest(input) === attempt.requestHash)
      const pending = await requireCommand(await platformApi.invokeTool({ tool_id: definition.tool,
        idempotency_key: attempt.requestKey, input: { ...input } }), attempt)
      requireRunPlan(pending.command.status === 'waiting_confirmation')
      const fixed = { ...attempt, commandId: pending.command.id }; acknowledge(fixed)
      return confirm(fixed)
    },
    async recover(attempt: EnvironmentRecordAttempt, plan: RunPlanArchive, binding: RunPlanBuildArchive, signal: AbortSignal) {
      verifyEnvironmentAttempt(attempt); signal.throwIfAborted()
      const value = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
        : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId,
          tool_id: definition.tool, request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
      const original = await requireCommand(value, attempt)
      requireRunPlan(generationEqual(original.input, environmentRequest(plan, binding)))
      signal.throwIfAborted(); return original
    },
    async read(command: ToolInvocation, plan: RunPlanArchive, binding: RunPlanBuildArchive, signal: AbortSignal) {
      requireRunPlan(command.status === 'completed' && command.result?.[definition.receipt])
      signal.throwIfAborted()
      const input = environmentRequest(plan, binding)
      await requireCommand(command, { projectId: input.project_id, planId: input.run_plan_id, planHash: input.run_plan_artifact_hash,
        bindingId: input.build_binding_id, bindingHash: input.build_binding_artifact_hash, commandId: command.id,
        requestKey: command.input_payload?.idempotency_key as string, requestHash: await canonicalDigest(input) })
      signal.throwIfAborted()
      const id = await definition.identity(command.id), project = plan.metadata.project_id
      const value = await request<unknown>(`/v1/projects/${encodeURIComponent(project)}/quality/${definition.path}/${encodeURIComponent(id)}`, { signal, cache: 'no-store' })
      const archive = await definition.verify(value, plan, binding, command.id, id)
      requireRunPlan(generationEqual(command.result[definition.receipt], { metadata: archive.metadata, historical_not_live: true }))
      signal.throwIfAborted(); return archive
    },
  }
}
