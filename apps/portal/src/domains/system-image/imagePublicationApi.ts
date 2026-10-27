import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ImageRevisionSummary } from './types/imageRevision'

const policy = 'nasus.image-publication.v1'
export const rollbackPolicy = 'nasus.image-rollback.v1'
export interface PublicationSelection { project_id: string; image_revision_id: string; image_artifact_hash: string; target_baseline_id: string }
export interface PublicationTarget extends PublicationSelection { expected_head_id: string | null; policy_revision: typeof policy }
export interface RollbackTarget extends PublicationSelection { expected_head_id: string; rollback_publication_id: string; policy_revision: typeof rollbackPolicy }
export interface PublicationHead {
  publication_id: string; project_id: string; baseline_id: string; image_revision_id: string; image_artifact_hash: string
  sequence: number; recorded_at: string; actor_id: string; quality_generation_authorized: false; release_authorized: false
}
export interface PublicationReview {
  review_id: string; project_id: string; baseline_id: string; image_revision_id: string; image_artifact_hash: string
  decision: 'approve' | 'reject'; reason: string; recorded_at: string; actor_id: string; preview_digest: string
}
export interface PublicationPreview {
  target: PublicationTarget | RollbackTarget; preview_digest: string; image: ImageRevisionSummary
  baseline: { project_id: string; baseline_id: string; kind: string }
  head: PublicationHead | null; review: PublicationReview | null; can_review: boolean
  readiness: { scope: 'knowledge_snapshot_only'; quality_generation_authorized: false; release_authorized: false; unverified_observation_count: number }
}
const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/system-image/publications`
const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
const sameSelection = (a: PublicationSelection, b: PublicationSelection) => a.project_id === b.project_id && a.image_revision_id === b.image_revision_id
  && a.image_artifact_hash === b.image_artifact_hash && a.target_baseline_id === b.target_baseline_id
export function verifyPublicationHead(head: PublicationHead | null, selection: Pick<PublicationSelection, 'project_id' | 'target_baseline_id'>) {
  if (head !== null && (head.project_id !== selection.project_id || head.baseline_id !== selection.target_baseline_id
      || !head.publication_id || !head.image_revision_id || !digest(head.image_artifact_hash)
      || !Number.isSafeInteger(head.sequence) || head.sequence < 1 || head.quality_generation_authorized !== false || head.release_authorized !== false)) {
    throw new Error('Publication head mismatch')
  }
}
export class StalePublication extends Error {}
export function verifyPublicationPreview(value: PublicationPreview, selection: PublicationSelection, expectedHead: string | null, expectedPolicy: string) {
  verifyPublicationHead(value.head, selection)
  if (!sameSelection(value.target, selection) || value.target.expected_head_id !== expectedHead || value.target.policy_revision !== expectedPolicy
      || (value.head?.publication_id ?? null) !== expectedHead || !digest(value.preview_digest) || typeof value.can_review !== 'boolean'
      || value.baseline.project_id !== selection.project_id || value.baseline.baseline_id !== selection.target_baseline_id
      || value.image.project_id !== selection.project_id || value.image.image_revision_id !== selection.image_revision_id || value.image.artifact_hash !== selection.image_artifact_hash
      || value.readiness.scope !== 'knowledge_snapshot_only' || value.readiness.quality_generation_authorized !== false || value.readiness.release_authorized !== false
      || !Number.isSafeInteger(value.readiness.unverified_observation_count) || value.readiness.unverified_observation_count < 0) throw new Error('Publication preview mismatch')
  if (value.review && (value.review.project_id !== selection.project_id || value.review.baseline_id !== selection.target_baseline_id
      || value.review.image_revision_id !== selection.image_revision_id || value.review.image_artifact_hash !== selection.image_artifact_hash
      || value.review.preview_digest !== value.preview_digest || !value.review.review_id || !['approve', 'reject'].includes(value.review.decision))) throw new Error('Publication review mismatch')
  return value
}
export const imagePublicationApi = {
  async preview(selection: PublicationSelection, signal: AbortSignal) {
    const history = await request<{ baseline: PublicationPreview['baseline']; head: PublicationHead | null }>(
      `${root(selection.project_id)}?${new URLSearchParams({ baseline_id: selection.target_baseline_id, limit: '1' })}`, { signal, cache: 'no-store' })
    if (history.baseline.project_id !== selection.project_id || history.baseline.baseline_id !== selection.target_baseline_id) throw new Error('Publication target mismatch')
    verifyPublicationHead(history.head, selection)
    const expectedHead = history.head?.publication_id ?? null
    const params = new URLSearchParams({ image_revision_id: selection.image_revision_id, image_artifact_hash: selection.image_artifact_hash,
      target_baseline_id: selection.target_baseline_id })
    if (expectedHead) params.set('expected_head_id', expectedHead)
    const value = await request<PublicationPreview>(`${root(selection.project_id)}/preview?${params}`, { signal, cache: 'no-store' })
    return verifyPublicationPreview(value, selection, expectedHead, policy)
  },
  async write(view: PublicationPreview, action: 'review' | 'publish', decision: 'approve' | 'reject', reason: string, attempt: string) {
    const rollback = view.target.policy_revision === rollbackPolicy
    const tool = rollback ? (action === 'review' ? 'system_image.revisions.review_rollback' : 'baseline.rollback')
      : (action === 'review' ? 'system_image.revisions.review_publication' : 'baseline.promote')
    const input = { ...view.target, expected_preview_digest: view.preview_digest,
      ...(action === 'review' ? { expected_review_id: view.review?.review_id ?? null, decision, reason } : { approval_id: view.review?.review_id }) }
    let result = await platformApi.invokeTool({ tool_id: tool, input, idempotency_key: attempt })
    const invocationId = result.id
    function verifyCommand(value: typeof result) {
      if (!invocationId || value.id !== invocationId || value.tool_id !== tool
          || Object.entries(input).some(([key, expected]) => value.input_payload[key] !== expected)
          || (value.result && value.result.invocation_id !== invocationId)) throw new Error('Publication command mismatch')
    }
    verifyCommand(result)
    if (action === 'review') {
      if (result.status !== 'waiting_confirmation') throw new Error('Publication review requires confirmation')
      result = await platformApi.confirmToolInvocation(result.id)
      verifyCommand(result)
    }
    if (result.result?.followup_reason === 'publication_inputs_changed') throw new StalePublication('Publication changed')
    const prefix = action === 'review' ? 'publication_review:' : 'image_publication:'
    const refs = result.result?.object_refs.filter((ref) => ref.startsWith(prefix)) ?? []
    if (result.status !== 'completed' || refs.length !== 1 || !refs[0].slice(prefix.length)) throw new Error('Publication was not acknowledged')
    return refs[0].slice(prefix.length)
  },
}
