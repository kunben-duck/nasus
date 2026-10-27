import { request } from '../../shared/api/client'
import { contextPackApi } from '../system-image/contextPackApi'
import { verifyScopeArchive } from './testDesignScopeValidation'
import { generationEqual } from './testDesignGenerationValidation'
import { verifyGenerationArchiveView } from './generationBatchResultValidation'
import { mappingDigest } from './testDesignMappingValidation'
import { verifyReviewDraftItem, verifyReviewDraftPage } from './testDesignReviewValidation'
import type { ScopeArchive } from './types/testDesignScope'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { ReviewDraftItem, ReviewDraftRequest } from './types/testDesignReview'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/quality`
export const testDesignReviewApi = {
  async page(projectId: string, afterId: string, signal: AbortSignal) {
    const input: ReviewDraftRequest = { project_id: projectId, after_id: afterId, limit: 3 }
    const params = new URLSearchParams({ after_id: afterId, limit: String(input.limit) })
    const value = await request<unknown>(`${root(projectId)}/test-design-review-drafts?${params}`, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    return verifyReviewDraftPage(value, input)
  },
  async draft(projectId: string, selected: ReviewDraftItem, signal: AbortSignal) {
    const { metadata: m, context_pin: pin } = verifyReviewDraftItem(selected, projectId)
    const context = await contextPackApi.read({ project_id: projectId, image_revision_id: pin.image_revision_id,
      image_artifact_hash: pin.image_artifact_hash }, pin.context_id, signal)
    if (context.metadata.artifact_hash !== pin.artifact_hash || context.metadata.input_digest !== pin.input_digest) throw new Error('Draft context changed')
    const scopeValue = await request<ScopeArchive>(`${root(projectId)}/test-design-scopes/${encodeURIComponent(m.scope_revision_id)}`, { signal, cache: 'no-store' })
    const scope = verifyScopeArchive(scopeValue, context, m.scope_revision_id)
    if (scope.revision.artifact_hash !== selected.scope_pin.artifact_hash || scope.revision.request_hash !== selected.scope_pin.request_hash) throw new Error('Draft scope changed')
    const value = await request<GenerationArchive>(`${root(projectId)}/test-design-results/${encodeURIComponent(m.generation_id)}`, { signal, cache: 'no-store' })
    // These are archive provenance pins, not access to an administrator's job.
    const archive = await verifyGenerationArchiveView(value, scope, { project_id: projectId, generation_id: m.generation_id,
      source_invocation_id: m.invocation_id, invocation_id: m.recovery_invocation_id ?? m.invocation_id })
    if (!generationEqual(archive.metadata, m) || !generationEqual(archive.result.context_pin, pin)
      || !generationEqual(archive.result.scope_pin, selected.scope_pin)
      || !['nasus.test-design-result.v3', 'nasus.test-design-result.v4'].includes(archive.result.schema)
        && await mappingDigest(archive.result) !== m.artifact_hash) throw new Error('Draft archive digest mismatch')
    signal.throwIfAborted()
    return archive
  },
}
