import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types'
import type { RawAssetRecord, SystemImageData } from './types'
import { isSourceRefreshCommandId, requireSourceRefreshAttempt } from './sourceRefreshRecovery'

const toolId = 'system_image.sources.ingest'
const id = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 128
  && value.trim() === value && !Array.from(value).some((character) => character.charCodeAt(0) < 32
    || (character.charCodeAt(0) >= 127 && character.charCodeAt(0) <= 159))
const hash = (value: unknown) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)

export interface SourceRefreshInput {
  project_id: string
  source_ids: string[]
  expected_manifest_id: string
  expected_manifest_hash: string
}
export interface SourceRefreshAttempt { input: SourceRefreshInput; requestKey: string; commandId?: string }

export function refreshableSources(projectId: string, image: SystemImageData): RawAssetRecord[] {
  if (!id(projectId) || image?.project?.id !== projectId || image.read_state?.mode !== 'working_draft'
      || image.visibility?.mode === 'source_filtered' || image.source_manifest?.project_id !== projectId
      || !id(image.source_manifest?.manifest_id) || !hash(image.source_manifest?.content_hash)
      || !Array.isArray(image.sources) || image.sources.some((source) => !source || source.project_id !== projectId
        || !id(source.id) || !['code', 'us_doc', 'test_asset'].includes(source.source_type))
      || new Set(image.sources.map((source) => source.id)).size !== image.sources.length) {
    throw new Error('Working sources could not be verified')
  }
  // Initial empty source slots have never been registered by a user or command.
  return image.sources.filter((source) => typeof source.registered_at === 'string' && source.registered_at.length > 0)
}

export function prepareSourceRefresh(projectId: string, image: SystemImageData, selected: string[]): SourceRefreshInput {
  const sources = new Set(refreshableSources(projectId, image).map((source) => source.id))
  if (!Array.isArray(selected) || !selected.length || selected.length > 100 || new Set(selected).size !== selected.length
      || selected.some((value) => !id(value) || !sources.has(value))) throw new Error('Select registered sources from the displayed manifest')
  return { project_id: projectId, source_ids: [...selected], expected_manifest_id: image.source_manifest!.manifest_id,
    expected_manifest_hash: image.source_manifest!.content_hash }
}

export function sourceRefreshScope(projectId: string, image: SystemImageData): string {
  const ids = refreshableSources(projectId, image).map((source) => source.id).sort()
  return JSON.stringify([projectId, image.source_manifest!.manifest_id, image.source_manifest!.content_hash, ids])
}

export function requireSourceRefreshCommand(value: ToolInvocation, attempt: SourceRefreshAttempt): ToolInvocation {
  requireSourceRefreshAttempt(attempt)
  const input = attempt.input, body = value?.input_payload
  if (!value || !isSourceRefreshCommandId(value.id) || (attempt.commandId && value.id !== attempt.commandId)
      || value.tool_id !== toolId || body?.idempotency_key !== attempt.requestKey
      || body.project_id !== input.project_id || body.expected_manifest_id !== input.expected_manifest_id
      || body.expected_manifest_hash !== input.expected_manifest_hash
      || JSON.stringify(body.source_ids) !== JSON.stringify(input.source_ids)
      || !['pending', 'running', 'completed', 'failed', 'cancelled'].includes(value.status)
      || (value.result && (value.result.invocation_id !== value.id || value.result.status !== value.status))) {
    throw new Error('Source refresh command differs from the selected sources')
  }
  if (value.status === 'completed') {
    const refs = value.result?.object_refs
    if (!Array.isArray(refs) || refs.length !== input.source_ids.length + 3 || refs[0] !== `project:${input.project_id}`
        || refs.at(-2) !== `source_manifest:${input.expected_manifest_id}`
        || !refs.at(-1)?.startsWith('source_manifest:') || !id(refs.at(-1)?.slice('source_manifest:'.length))
        || new Set(refs.slice(1, -2)).size !== input.source_ids.length
        || refs.slice(1, -2).some((ref) => !input.source_ids.some((source) => ref === `raw_asset:${source}`))
        || JSON.stringify(value.result?.next_recommended_tools) !== JSON.stringify(['system_image.build.structure'])) {
      throw new Error('Source refresh receipt could not be verified')
    }
  }
  return value
}

export const sourceRefreshApi = {
  async submit(attempt: SourceRefreshAttempt) {
    requireSourceRefreshAttempt(attempt)
    if (attempt.commandId) throw new Error('An acknowledged source refresh must not be submitted again')
    return requireSourceRefreshCommand(await platformApi.invokeTool({ tool_id: toolId,
      idempotency_key: attempt.requestKey, input: { ...attempt.input } }), attempt)
  },
  async recover(attempt: SourceRefreshAttempt, signal: AbortSignal) {
    requireSourceRefreshAttempt(attempt)
    signal.throwIfAborted()
    if (attempt.commandId) {
      const command = await platformApi.getToolInvocation(attempt.commandId, { signal })
      signal.throwIfAborted()
      return requireSourceRefreshCommand(command, attempt)
    }
    const original = await request<ToolInvocation | null>(`/v1/tool-invocations/resolve?${new URLSearchParams({
      project_id: attempt.input.project_id, tool_id: toolId, request_key: attempt.requestKey,
    })}`,
      { signal, cache: 'no-store' })
    signal.throwIfAborted()
    if (!original) throw new Error('Original source refresh acknowledgement could not be verified')
    const resolved = requireSourceRefreshCommand(original, attempt)
    const command = await platformApi.getToolInvocation(resolved.id, { signal })
    signal.throwIfAborted()
    return requireSourceRefreshCommand(command, { ...attempt, commandId: resolved.id })
  },
}
