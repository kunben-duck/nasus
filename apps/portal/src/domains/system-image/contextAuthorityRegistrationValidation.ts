export interface ContextAuthorityRegistrationRequest {
  project_id: string
  context_id: string
  artifact_hash: string
  policy_revision: 'nasus.context-authority-dependencies.v1'
}
export interface ContextAuthorityBackfillItem {
  registration_request: ContextAuthorityRegistrationRequest
  image_revision_id: string
  image_artifact_hash: string
  status: 'requires_independent_confirmation'
}
export interface ContextAuthorityBackfillPage {
  items: ContextAuthorityBackfillItem[]
  next_after_id: string | null
  generation_authorized: false
}

export const contextRegistrationId = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0 && value.length <= 128 && [...value].every((char) => char.charCodeAt(0) >= 32)
const digest = (value: unknown): value is string => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
function requireValue(valid: unknown): asserts valid { if (!valid) throw new Error('Historical context dependency page could not be verified') }

export function verifyContextAuthorityBackfillPage(value: unknown, projectId: string, afterId: string, limit = 3): ContextAuthorityBackfillPage {
  const v = value as ContextAuthorityBackfillPage
  requireValue(contextRegistrationId(projectId) && typeof afterId === 'string' && afterId.length <= 128 && Number.isSafeInteger(limit) && limit >= 1 && limit <= 5
    && v && Object.keys(v).length === 3 && Array.isArray(v.items) && v.items.length <= limit && v.generation_authorized === false)
  let previous = afterId
  for (const item of v.items) {
    const r = item?.registration_request
    requireValue(item && Object.keys(item).length === 4 && r && Object.keys(r).length === 4
      && r.project_id === projectId && contextRegistrationId(r.context_id) && r.context_id > previous && digest(r.artifact_hash)
      && r.policy_revision === 'nasus.context-authority-dependencies.v1' && contextRegistrationId(item.image_revision_id) && digest(item.image_artifact_hash)
      && item.status === 'requires_independent_confirmation')
    previous = r.context_id
  }
  requireValue(v.next_after_id === null || contextRegistrationId(v.next_after_id) && v.items.length === limit && v.next_after_id === previous)
  return v
}
