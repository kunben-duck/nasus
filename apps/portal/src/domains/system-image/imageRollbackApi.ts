import { request } from '../../shared/api/client'
import { rollbackPolicy, verifyPublicationHead, verifyPublicationPreview, type PublicationHead, type PublicationPreview, type RollbackTarget } from './imagePublicationApi'

export interface PublicationHistory {
  baseline: PublicationPreview['baseline']; head: PublicationHead | null
  items: PublicationHead[]; next_after_sequence: number | null
}
export interface RollbackPreview extends PublicationPreview { target: RollbackTarget; rollback_source: PublicationHead }
const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/system-image/publications`

export function verifyRollbackHistory(value: PublicationHistory, projectId: string, baselineId: string, after: number) {
  const selection = { project_id: projectId, target_baseline_id: baselineId }
  if (!Number.isSafeInteger(after) || after < 0 || value.baseline.project_id !== projectId || value.baseline.baseline_id !== baselineId
      || !Array.isArray(value.items) || value.items.length > 10) throw new Error('Rollback history scope mismatch')
  verifyPublicationHead(value.head, selection)
  let sequence = after
  const ids = new Set<string>()
  for (const item of value.items) {
    verifyPublicationHead(item, selection)
    if (item === null || item.sequence <= sequence || ids.has(item.publication_id) || !value.head || item.sequence > value.head.sequence) throw new Error('Rollback history ordering mismatch')
    ids.add(item.publication_id)
    sequence = item.sequence
  }
  if (value.next_after_sequence !== null && (value.items.length !== 10 || value.next_after_sequence !== sequence)) throw new Error('Rollback history cursor mismatch')
  return value
}

export const imageRollbackApi = {
  async history(projectId: string, baselineId: string, after: number, signal: AbortSignal) {
    const value = await request<PublicationHistory>(`${root(projectId)}?${new URLSearchParams({ baseline_id: baselineId,
      after_sequence: String(after), limit: '10' })}`, { signal, cache: 'no-store' })
    return verifyRollbackHistory(value, projectId, baselineId, after)
  },
  async preview(target: RollbackTarget, signal: AbortSignal) {
    const params = new URLSearchParams({ image_revision_id: target.image_revision_id, image_artifact_hash: target.image_artifact_hash,
      target_baseline_id: target.target_baseline_id, expected_head_id: target.expected_head_id, rollback_publication_id: target.rollback_publication_id })
    const value = await request<RollbackPreview>(`${root(target.project_id)}/rollback-preview?${params}`, { signal, cache: 'no-store' })
    verifyPublicationPreview(value, target, target.expected_head_id, rollbackPolicy)
    verifyPublicationHead(value.rollback_source, target)
    if (value.target.rollback_publication_id !== target.rollback_publication_id || !value.head
        || value.rollback_source.publication_id !== target.rollback_publication_id
        || value.rollback_source.image_revision_id !== target.image_revision_id || value.rollback_source.image_artifact_hash !== target.image_artifact_hash
        || value.rollback_source.sequence >= value.head.sequence || value.rollback_source.image_revision_id === value.head.image_revision_id) throw new Error('Rollback source mismatch')
    return value
  },
}
