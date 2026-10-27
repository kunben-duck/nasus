import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { requireScript, verifyScriptArchive, verifyScriptHistory, verifyScriptPreview } from './automationScriptValidation'
import { verifyScriptReviewArchive, verifyScriptReviewView } from './automationScriptReviewValidation'
import type { ToolInvocation } from '../platform/types'
import type { AutomationInputPreview } from './types/automationInput'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'
import type { ScriptArchive, ScriptHistoryItem, ScriptHistoryRequest, ScriptPreview, ScriptReviewRequest, ScriptReviewRevision, ScriptSelection } from './types/automationScripts'

const generate = 'quality.automation.generate', review = 'quality.automation.review'
function exact(command: ToolInvocation, tool: string, input: object) {
  return command && typeof command.id === 'string' && !!command.id && command.tool_id === tool
    && Object.entries(input).every(([key, value]) => generationEqual(command.input_payload?.[key], value))
}
async function confirmed(tool: string, input: object, attempt: string, onCommand?: (id: string) => void) {
  const pending = await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt, input: { ...input } })
  requireScript(exact(pending, tool, input) && pending.status === 'waiting_confirmation')
  onCommand?.(pending.id)
  const done = await platformApi.confirmToolInvocation(pending.id)
  requireScript(done.id === pending.id && exact(done, tool, input) && done.input_payload.confirmed_by_user === true && done.status === 'completed'
    && done.result?.object_refs.length === 1 && done.result.object_refs[0].startsWith(tool === generate ? 'automation_script_revision:' : 'automation_script_review:'))
  return done.id
}
export const automationScriptApi = {
  async preview(selection: ScriptSelection, prepared: AutomationInputPreview) {
    const value = await platformApi.invokeTool({ tool_id: 'query.quality.automation_execution', idempotency_key: crypto.randomUUID(), input: { ...selection } })
    requireScript(exact(value, 'query.quality.automation_execution', selection) && value.status === 'completed')
    return verifyScriptPreview(value.result?.automation_execution_preview, selection, prepared)
  },
  generate: (preview: ScriptPreview, attempt: string, onCommand: (id: string) => void) => confirmed(generate, preview.request, attempt, onCommand),
  review: (input: ScriptReviewRequest, attempt: string) => confirmed(review, input, attempt),
  async history(mapping: RecordedMappingArchive, after: string, signal: AbortSignal) {
    signal.throwIfAborted()
    const input: ScriptHistoryRequest = { project_id: mapping.revision.project_id, mapping_revision_id: mapping.revision.revision_id,
      mapping_artifact_hash: mapping.revision.artifact_hash, after_id: after, limit: 10 }
    const params = new URLSearchParams({ mapping_revision_id: input.mapping_revision_id, mapping_artifact_hash: input.mapping_artifact_hash,
      after_id: after, limit: String(input.limit) })
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/automation-script-history?${params}`, { signal, cache: 'no-store' })
    const result = verifyScriptHistory(value, input); signal.throwIfAborted(); return result
  },
  async read(draft: GenerationArchive, mapping: RecordedMappingArchive, item: ScriptHistoryItem, signal: AbortSignal) {
    signal.throwIfAborted(); requireScript(item.script_revision_id && item.artifact_hash)
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(mapping.revision.project_id)}/quality/automation-script-revisions/${encodeURIComponent(item.script_revision_id)}`, { signal, cache: 'no-store' })
    const result = await verifyScriptArchive(value, draft, mapping, item); signal.throwIfAborted(); return result
  },
  async inspect(draft: ScriptArchive, signal: AbortSignal) {
    signal.throwIfAborted()
    const m = draft.metadata, params = new URLSearchParams({ artifact_hash: m.artifact_hash })
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(m.project_id)}/quality/automation-script-revisions/${encodeURIComponent(m.script_revision_id)}/review?${params}`, { signal, cache: 'no-store' })
    const result = await verifyScriptReviewView(value, draft); signal.throwIfAborted(); return result
  },
  async readReview(draft: ScriptArchive, revision: ScriptReviewRevision, signal: AbortSignal) {
    signal.throwIfAborted()
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(draft.metadata.project_id)}/quality/automation-script-reviews/${encodeURIComponent(revision.revision_id)}`, { signal, cache: 'no-store' })
    const result = await verifyScriptReviewArchive(value, draft)
    requireScript(generationEqual(result.revision, revision)); signal.throwIfAborted(); return result
  },
}
