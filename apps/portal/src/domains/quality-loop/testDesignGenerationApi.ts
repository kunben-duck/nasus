import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types'
import type { ScopeArchive } from './types/testDesignScope'
import type { GenerationHistoryRequest, GenerationJob, GenerationPreview, GenerationRecovery, GenerationSelection } from './types/testDesignGeneration'
import { generationEqual, verifyGenerationHistory, verifyGenerationJob, verifyGenerationPreview } from './testDesignGenerationValidation'
import { verifyGenerationArchiveView } from './generationBatchResultValidation'
import { verifyBatchGenerationPreview } from './generationBatchPreviewValidation'

const generate = 'quality.test_design.generate', recover = 'quality.test_design.recover'
function matches(item: ToolInvocation, tool: string, input: object) {
  return item && typeof item.id === 'string' && !!item.id && item.tool_id === tool
    && Object.entries(input).every(([key, value]) => generationEqual(item.input_payload?.[key], value))
}
async function confirmed(tool: string, input: object, attempt: string) {
  const pending = await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt, input: { ...input } })
  if (!matches(pending, tool, input) || pending.status !== 'waiting_confirmation') throw new Error('Exact generation confirmation required')
  const accepted = await platformApi.confirmToolInvocation(pending.id)
  if (accepted.id !== pending.id || !matches(accepted, tool, input) || accepted.input_payload.confirmed_by_user !== true
    || !['running', 'completed'].includes(accepted.status)) {
    throw new Error('Generation dispatch was not acknowledged; inspect history before retrying')
  }
  return accepted.id
}
export const testDesignGenerationApi = {
  async preview(selection: GenerationSelection) {
    const tool = selection.budget.max_calls > 1 ? 'query.quality.test_design_batches' : 'query.quality.test_design_execution'
    const result = await platformApi.invokeTool({ tool_id: tool, idempotency_key: crypto.randomUUID(), input: { ...selection } })
    if (!matches(result, tool, selection) || result.status !== 'completed') throw new Error('Generation preflight unavailable')
    return selection.budget.max_calls > 1 ? verifyBatchGenerationPreview(result.result?.test_design_execution_preview, selection)
      : verifyGenerationPreview(result.result?.test_design_execution_preview, selection)
  },
  start: (preview: GenerationPreview, attempt: string) => confirmed(generate, preview.request, attempt),
  recover: (input: GenerationRecovery, attempt: string) => confirmed(recover, input, attempt),
  async cancel(projectId: string, id: string, attempt: string) {
    const input = { project_id: projectId, invocation_id: id }, tool = 'quality.test_design.cancel'
    const pending = await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt, input })
    if (!matches(pending, tool, input) || pending.status !== 'waiting_confirmation') throw new Error('Exact cancellation confirmation required')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.id !== pending.id || !matches(done, tool, input) || done.input_payload.confirmed_by_user !== true
      || done.status !== 'completed') throw new Error('Cancellation was not acknowledged')
  },
  async historyPage(scope: ScopeArchive, afterId: string, signal: AbortSignal) {
    const input: GenerationHistoryRequest = { project_id: scope.revision.project_id, scope_revision_id: scope.revision.revision_id,
      scope_artifact_hash: scope.revision.artifact_hash, after_id: afterId, limit: 20 }
    const params = new URLSearchParams({ scope_revision_id: input.scope_revision_id, scope_artifact_hash: input.scope_artifact_hash,
      after_id: input.after_id, limit: String(input.limit) })
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/test-design-jobs?${params}`,
      { signal, cache: 'no-store' })
    return verifyGenerationHistory(value, input)
  },
  async job(scope: ScopeArchive, id: string, signal: AbortSignal) {
    signal.throwIfAborted()
    const input = { project_id: scope.revision.project_id, invocation_id: id }, tool = 'query.quality.test_design_job'
    const result = await platformApi.invokeTool({ tool_id: tool, idempotency_key: crypto.randomUUID(), input })
    signal.throwIfAborted()
    if (!matches(result, tool, input) || result.status !== 'completed') throw new Error('Generation job access unavailable')
    return verifyGenerationJob(result.result?.test_design_job, scope, id)
  },
  async result(scope: ScopeArchive, job: GenerationJob, signal: AbortSignal) {
    if (!job.generation_id) throw new Error('Generation has no committed draft')
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(scope.revision.project_id)}/quality/test-design-results/${encodeURIComponent(job.generation_id)}`,
      { signal, cache: 'no-store' })
    const archive = await verifyGenerationArchiveView(value, scope, job)
    signal.throwIfAborted()
    return archive
  },
}
