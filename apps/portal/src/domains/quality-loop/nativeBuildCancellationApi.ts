import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types'
import { scriptId } from './automationScriptValidation'
import { verifyNativeAttempt } from './nativeBuildRecovery'
import { requireNativeBuild } from './nativeBuildValidation'
import type { NativeBuildAttempt } from './types/nativeBuilds'

export const nativeCancelTool = 'quality.native_build.cancel'
export interface NativeCancellationReceipt {
  project_id: string; invocation_id: string; status: 'completed' | 'failed' | 'cancelled'
  cancellation_requested: boolean; cleanup_confirmed: false; execution_authorized: false
}
async function requireTarget(attempt: NativeBuildAttempt, targetId: string) {
  verifyNativeAttempt(attempt)
  requireNativeBuild(scriptId(targetId) && await canonicalDigest({ project_id: attempt.projectId, invocation_id: targetId }) === attempt.requestHash)
}
export async function verifyNativeCancellation(value: ToolInvocation, attempt: NativeBuildAttempt, targetId: string) {
  verifyNativeAttempt(attempt)
  const input = { project_id: attempt.projectId, invocation_id: targetId }, body = value?.input_payload
  requireNativeBuild(scriptId(targetId) && scriptId(value?.id) && value.id !== targetId
    && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === nativeCancelTool
    && body?.project_id === input.project_id && body.invocation_id === targetId && body.idempotency_key === attempt.requestKey
    && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
  let receipt: NativeCancellationReceipt | undefined
  if (value.status === 'waiting_confirmation') requireNativeBuild(!value.result && body.confirmed_by_user !== true)
  if (value.status === 'completed') {
    receipt = value.result?.native_build_job as NativeCancellationReceipt | undefined
    requireNativeBuild(body.confirmed_by_user === true && value.result?.invocation_id === value.id && value.result.status === 'completed'
      && value.result.object_refs.length === 0 && receipt?.project_id === input.project_id && receipt.invocation_id === targetId
      && ['completed', 'failed', 'cancelled'].includes(receipt.status) && typeof receipt.cancellation_requested === 'boolean'
      && receipt.cancellation_requested === (receipt.status === 'cancelled')
      && receipt.cleanup_confirmed === false && receipt.execution_authorized === false)
  }
  return { command: value, receipt }
}
export const nativeBuildCancellationApi = {
  async create(attempt: NativeBuildAttempt, targetId: string, acknowledge: (value: NativeBuildAttempt) => void, requireScope: () => void) {
    await requireTarget(attempt, targetId); requireNativeBuild(!attempt.commandId); requireScope()
    const value = await verifyNativeCancellation(await platformApi.invokeTool({ tool_id: nativeCancelTool, idempotency_key: attempt.requestKey,
      input: { project_id: attempt.projectId, invocation_id: targetId } }), attempt, targetId)
    requireNativeBuild(value.command.status === 'waiting_confirmation')
    const fixed = { ...attempt, commandId: value.command.id }; acknowledge(fixed); requireScope()
    return this.confirm(fixed, targetId, requireScope)
  },
  async confirm(attempt: NativeBuildAttempt, targetId: string, requireScope: () => void) {
    await requireTarget(attempt, targetId); requireNativeBuild(attempt.commandId); requireScope()
    const original = await verifyNativeCancellation(await platformApi.getToolInvocation(attempt.commandId), attempt, targetId)
    requireNativeBuild(original.command.status === 'waiting_confirmation'); requireScope()
    const value = await platformApi.confirmToolInvocation(attempt.commandId)
    requireScope(); return verifyNativeCancellation(value, attempt, targetId)
  },
  async recover(attempt: NativeBuildAttempt, targetId: string, signal: AbortSignal) {
    await requireTarget(attempt, targetId); signal.throwIfAborted()
    const value = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId, tool_id: nativeCancelTool, request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    signal.throwIfAborted(); return verifyNativeCancellation(value, attempt, targetId)
  },
}
