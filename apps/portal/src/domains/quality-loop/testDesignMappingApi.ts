import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { verifyMappingArchive, verifyMappingView } from './testDesignMappingValidation'
import type { ToolInvocation } from '../platform/types'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { MappingReview, MappingRevision } from './types/testDesignMapping'

const tool = 'quality.test_design_mapping.review'
export class StaleTestDesignMapping extends Error {}
function exact(command: ToolInvocation, input: MappingReview) {
  return command && command.tool_id === tool && typeof command.id === 'string' && !!command.id
    && Object.entries(input).every(([key, value]) => generationEqual(command.input_payload?.[key], value))
}
export const testDesignMappingApi = {
  async inspect(draft: GenerationArchive, signal: AbortSignal) {
    const m = draft.metadata, query = new URLSearchParams({ artifact_hash: m.artifact_hash })
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(m.project_id)}/quality/test-design-results/${encodeURIComponent(m.generation_id)}/mapping-review?${query}`,
      { signal, cache: 'no-store' })
    const result = await verifyMappingView(value, draft)
    signal.throwIfAborted(); return result
  },
  async read(draft: GenerationArchive, revision: MappingRevision, signal: AbortSignal) {
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(draft.metadata.project_id)}/quality/test-design-mapping-reviews/${encodeURIComponent(revision.revision_id)}`,
      { signal, cache: 'no-store' })
    const result = await verifyMappingArchive(value, draft, revision)
    signal.throwIfAborted(); return result
  },
  async record(input: MappingReview, attempt: string) {
    const pending = await platformApi.invokeTool({ tool_id: tool, input: { ...input }, idempotency_key: attempt })
    if (!exact(pending, input) || pending.status !== 'waiting_confirmation') throw new Error('Exact mapping confirmation required')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.result?.followup_reason === 'test_design_mapping_changed') throw new StaleTestDesignMapping('Mapping inputs changed')
    if (done.id !== pending.id || !exact(done, input) || done.input_payload.confirmed_by_user !== true || done.status !== 'completed'
      || done.result?.object_refs.length !== 1 || !done.result.object_refs[0].startsWith('test_design_mapping:')) throw new Error('Mapping review not acknowledged')
    return done.id
  },
}
