import { platformApi } from '../platform/api'
import type { SemanticReviewPage } from './types/semanticReview'
import { StaleSemanticReview } from './semanticReviewApi'

export const semanticMembershipApi = {
  async freeze(page: SemanticReviewPage, attempt: string) {
    if (!page.head || page.head.decision_id !== page.head_decision_id || page.head.claim_id !== page.assertion.claim_id) {
      throw new Error('An exact reviewed claim is required')
    }
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.revisions.freeze_semantic', idempotency_key: attempt, input: {
      project_id: page.assertion.project_id, parent_revision_id: page.assertion.image_revision_id,
      parent_artifact_hash: page.assertion.image_artifact_hash, decision_ids: [page.head_decision_id],
    } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Semantic freeze requires separate confirmation')
    const result = await platformApi.confirmToolInvocation(pending.id)
    if (result.result?.followup_reason === 'stale_semantic_decision') throw new StaleSemanticReview('Review changed before freeze')
    if (result.status !== 'completed') throw new Error('Semantic freeze was not acknowledged')
    const revision = result.result?.object_refs?.find((ref) => ref.startsWith('image_revision:'))?.slice('image_revision:'.length)
    if (!revision) throw new Error('Missing semantic freeze receipt')
    return revision
  },
}
