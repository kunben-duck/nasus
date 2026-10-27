import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { verifyGenerationMetadata } from './generationResultMetadata'
import type { ReviewDraftItem, ReviewDraftPage, ReviewDraftRequest } from './types/testDesignReview'

const id = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 128
function requireValue(valid: unknown): asserts valid { if (!valid) throw new Error('Draft discovery could not be verified') }

export function verifyReviewDraftItem(value: unknown, projectId: string): ReviewDraftItem {
  const v = value as ReviewDraftItem, m = v?.metadata, c = v?.context_pin, s = v?.scope_pin
  requireValue(v && Object.keys(v).length === 3 && m && c && s && m.project_id === projectId
    && verifyGenerationMetadata(m)
    && Object.keys(c).length === 5 && [c.context_id, c.image_revision_id].every(id)
    && [c.artifact_hash, c.input_digest, c.image_artifact_hash].every(generationDigest)
    && Object.keys(s).length === 3 && s.revision_id === m.scope_revision_id && [s.artifact_hash, s.request_hash].every(generationDigest))
  return v
}

export function verifyReviewDraftPage(value: unknown, request: ReviewDraftRequest): ReviewDraftPage {
  const v = value as ReviewDraftPage
  requireValue(v && Object.keys(v).length === 6 && generationEqual(v.request, request) && Object.keys(request).length === 3
    && id(request.project_id) && typeof request.after_id === 'string' && request.after_id.length <= 128
    && Number.isSafeInteger(request.limit) && request.limit >= 1 && request.limit <= 5
    && Array.isArray(v.items) && v.items.length <= request.limit && v.can_review === true
    && v.generation_authorized === false && v.execution_authorized === false)
  let previous = request.after_id
  for (const item of v.items) {
    verifyReviewDraftItem(item, request.project_id)
    requireValue(item.metadata.generation_id > previous)
    previous = item.metadata.generation_id
  }
  requireValue(v.next_after_id === null || id(v.next_after_id) && v.items.length === request.limit && v.next_after_id === previous)
  return v
}
