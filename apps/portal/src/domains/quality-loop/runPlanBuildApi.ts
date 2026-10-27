import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import { verifyBuildAttempt } from './runPlanBuildRecovery'
import { buildRequestKeys, bindingSelection, expectedBuildBinding, originalCodeSources, verifyBuildArchive, verifyBuildPreview, verifyNativeBuild } from './runPlanBuildValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { NativeBuildView, RunPlanBuildAttempt, RunPlanBuildRequest, RunPlanBuildSelection } from './types/runPlanBuilds'

export const buildBindingTool = 'quality.run_plan.bind_native_build'
export async function requireBuildCommand(value: ToolInvocation, attempt: RunPlanBuildAttempt) {
  verifyBuildAttempt(attempt)
  const body = value?.input_payload, input = Object.fromEntries(buildRequestKeys.map((key) => [key, body?.[key]])) as unknown as RunPlanBuildRequest
  requireRunPlan(value && scriptId(value.id) && (!attempt.commandId || attempt.commandId === value.id) && value.tool_id === buildBindingTool
    && body?.idempotency_key === attempt.requestKey && input.project_id === attempt.projectId && input.run_plan_id === attempt.planId
    && input.run_plan_artifact_hash === attempt.planHash && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
  if (value.status === 'completed') requireRunPlan(body.confirmed_by_user === true && value.result?.status === 'completed'
    && value.result.invocation_id === value.id && value.result.object_refs.length === 1 && value.result.object_refs[0].startsWith('run_plan_build:')
    && scriptId(value.result.object_refs[0].slice('run_plan_build:'.length)))
  return { command: value, input }
}
export async function readOriginalBuilds(plan: RunPlanArchive, ids: string[], signal: AbortSignal): Promise<NativeBuildView[]> {
  requireRunPlan(ids.length === originalCodeSources(plan).length && ids.length > 0 && ids.length <= 1000 && ids.every(scriptId) && new Set(ids).size === ids.length)
  const values: NativeBuildView[] = []
  for (const id of ids) {
    signal.throwIfAborted()
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(plan.metadata.project_id)}/quality/native-builds/${encodeURIComponent(id)}`, { signal, cache: 'no-store' })
    values.push(await verifyNativeBuild(value, plan.metadata.project_id, id))
  }
  signal.throwIfAborted(); return values
}
export const runPlanBuildApi = {
  async preview(selection: RunPlanBuildSelection, plan: RunPlanArchive, builds: NativeBuildView[]) {
    const command = await platformApi.invokeTool({ tool_id: 'query.quality.run_plan_build_preview', idempotency_key: crypto.randomUUID(), input: { ...selection } })
    requireRunPlan(scriptId(command?.id) && command.tool_id === 'query.quality.run_plan_build_preview' && command.status === 'completed'
      && Object.entries(selection).every(([key, value]) => generationEqual(command.input_payload[key], value)))
    return verifyBuildPreview(command.result?.run_plan_build_preview, plan, selection, builds)
  },
  async bind(input: RunPlanBuildRequest, attempt: RunPlanBuildAttempt, acknowledge: (value: RunPlanBuildAttempt) => void) {
    requireRunPlan(!attempt.commandId && await canonicalDigest(input) === attempt.requestHash)
    const pending = await requireBuildCommand(await platformApi.invokeTool({ tool_id: buildBindingTool, idempotency_key: attempt.requestKey, input: { ...input } }), attempt)
    requireRunPlan(pending.command.status === 'waiting_confirmation')
    const fixed = { ...attempt, commandId: pending.command.id }; acknowledge(fixed)
    return this.confirm(fixed)
  },
  async confirm(attempt: RunPlanBuildAttempt) {
    requireRunPlan(attempt.commandId)
    return requireBuildCommand(await platformApi.confirmToolInvocation(attempt.commandId), attempt)
  },
  async recover(attempt: RunPlanBuildAttempt, plan: RunPlanArchive, signal: AbortSignal) {
    verifyBuildAttempt(attempt); signal.throwIfAborted()
    const value = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId,
        tool_id: buildBindingTool, request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    const original = await requireBuildCommand(value, attempt)
    const builds = await readOriginalBuilds(plan, original.input.native_builds.map((b) => b.invocation_id), signal)
    const expected = await expectedBuildBinding(plan, bindingSelection(original.input), builds)
    requireRunPlan(expected.binding_digest === original.input.binding_digest)
    signal.throwIfAborted(); return { ...original, builds }
  },
  async read(command: ToolInvocation, input: RunPlanBuildRequest, plan: RunPlanArchive, builds: NativeBuildView[], signal: AbortSignal) {
    requireRunPlan(command.status === 'completed' && command.result?.object_refs.length === 1)
    signal.throwIfAborted(); const id = command.result!.object_refs[0].slice('run_plan_build:'.length)
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/run-plan-builds/${encodeURIComponent(id)}`, { signal, cache: 'no-store' })
    const archive = await verifyBuildArchive(value, input, command.id, plan, builds)
    requireRunPlan(archive.metadata.binding_id === id); signal.throwIfAborted(); return archive
  },
}
