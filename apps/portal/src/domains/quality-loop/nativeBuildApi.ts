import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { verifyNativeAttempt } from './nativeBuildRecovery'
import { nativeCommandKeys, nativeSelectionKeys, requireNativeBuild, requireNativeCommand, verifyNativeJob, verifyNativePreview } from './nativeBuildValidation'
import type { FrozenImageSources } from '../system-image/frozenImageSources'
import type { ToolInvocation } from '../platform/types'
import type { NativeBuildAttempt, NativeBuildCommand, NativeBuildSelection } from './types/nativeBuilds'

export const nativeBuildTool = 'quality.native_build.prepare'
export async function requireNativeInvocation(value: ToolInvocation, attempt: NativeBuildAttempt, sources: FrozenImageSources) {
  verifyNativeAttempt(attempt)
  const body = value?.input_payload, input = Object.fromEntries(nativeCommandKeys.map((key) => [key, body?.[key]])) as unknown as NativeBuildCommand
  requireNativeCommand(input, sources)
  requireNativeBuild(value && scriptId(value.id) && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === nativeBuildTool
    && body?.idempotency_key === attempt.requestKey && input.project_id === attempt.projectId && input.image_revision_id === attempt.imageId
    && input.image_artifact_hash === attempt.imageHash && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
  if (value.status === 'completed') requireNativeBuild(body.confirmed_by_user === true && value.result?.status === 'completed'
    && value.result.invocation_id === value.id && value.result.object_refs.length === 1 && value.result.object_refs[0].startsWith('native_build:')
    && scriptId(value.result.object_refs[0].slice('native_build:'.length)))
  return { command: value, input }
}
export const nativeBuildApi = {
  async preview(selection: NativeBuildSelection, sources: FrozenImageSources, requireScope: () => void) {
    requireScope()
    const command = await platformApi.invokeTool({ tool_id: 'query.quality.native_build_preview', idempotency_key: crypto.randomUUID(), input: { ...selection } })
    requireScope()
    requireNativeBuild(scriptId(command?.id) && command.tool_id === 'query.quality.native_build_preview' && command.status === 'completed'
      && nativeSelectionKeys.every((key) => generationEqual(command.input_payload[key], selection[key])))
    return verifyNativePreview(command.result?.native_build_preview, selection, sources)
  },
  async prepare(input: NativeBuildCommand, attempt: NativeBuildAttempt, sources: FrozenImageSources,
    acknowledge: (value: NativeBuildAttempt) => void, requireScope: () => void) {
    requireNativeBuild(!attempt.commandId && await canonicalDigest(input) === attempt.requestHash); requireScope()
    const pending = await requireNativeInvocation(await platformApi.invokeTool({ tool_id: nativeBuildTool, idempotency_key: attempt.requestKey, input: { ...input } }), attempt, sources)
    requireNativeBuild(pending.command.status === 'waiting_confirmation')
    const fixed = { ...attempt, commandId: pending.command.id }; acknowledge(fixed); requireScope()
    return this.confirm(fixed, sources, requireScope)
  },
  async confirm(attempt: NativeBuildAttempt, sources: FrozenImageSources, requireScope: () => void) {
    requireNativeBuild(attempt.commandId); requireScope()
    const value = await platformApi.confirmToolInvocation(attempt.commandId)
    requireScope(); return requireNativeInvocation(value, attempt, sources)
  },
  async recover(attempt: NativeBuildAttempt, sources: FrozenImageSources, signal: AbortSignal) {
    verifyNativeAttempt(attempt); signal.throwIfAborted()
    const command = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId, tool_id: nativeBuildTool, request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    signal.throwIfAborted(); const original = await requireNativeInvocation(command, attempt, sources)
    if (command.input_payload.confirmed_by_user !== true) {
      requireNativeBuild(['waiting_confirmation', 'cancelled', 'failed'].includes(command.status)); return { ...original, view: null }
    }
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(attempt.projectId)}/quality/native-builds/${encodeURIComponent(command.id)}`, { signal, cache: 'no-store' })
    const view = await verifyNativeJob(value, original.input, command.id, command.status, sources)
    if (command.status === 'completed') requireNativeBuild(view.metadata && command.result?.object_refs[0] === 'native_build:' + view.metadata.build_id)
    signal.throwIfAborted(); return { ...original, view }
  },
}
