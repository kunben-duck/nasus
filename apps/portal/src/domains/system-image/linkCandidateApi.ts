import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ImageObjectMember } from './types/imageRevision'
import type { SemanticScreeningItem } from './types/semanticEvaluation'

export type LinkRelation = 'implements' | 'asserts'
export interface LinkCandidateEndpoint {
  object_id: string; revision_id: string; source_revision_id: string; kind: string
  title: string; content_hash: string; evidence_ids: string[]
}
export interface LinkCandidatePage {
  project_id: string; image_revision_id: string; image_artifact_hash: string
  target: LinkCandidateEndpoint; relation: LinkRelation
  items: { endpoint: LinkCandidateEndpoint; retrieval_score: number; signals: string[]; status: 'retrieved_not_asserted'; calibrated_probability: null
    review_status: 'unreviewed' | 'requires_revalidation' | 'reviewed_not_approved' }[]
  eligible_count: number; matched_count: number; excluded: Record<string, number>; truncated: boolean
  method_version: 'nasus.link-recall.reviewed.v2'; authority_status: 'pending_confirmation'
  requested_limit: number; pre_review_matched_count: number; review_scope_digest: string
  review_scope: 'pinned_query_heads_not_live'; review_screening: SemanticScreeningItem[]
  semantic_status: 'retrieval_only_not_implementation_or_coverage'; limitations: string[]
}

export const linkCandidateApi = {
  async recall(project: string, revision: string, target: string, relation: LinkRelation, limit: number) {
    const invocation = await platformApi.invokeTool({ tool_id: 'query.system_image.links.screened_candidates', idempotency_key: crypto.randomUUID(), input: {
      project_id: project, image_revision_id: revision, target_object_id: target, relation, limit,
      method_version: 'nasus.link-recall.reviewed.v2',
    } })
    if (invocation.status !== 'completed') throw new Error('Candidate recall failed')
    return { invocationId: invocation.id, relation, limit }
  },
  async expand(project: string, revision: string, target: ImageObjectMember, selection: { invocationId: string; relation: LinkRelation; limit: number }, signal: AbortSignal) {
    const page = await request<LinkCandidatePage>(`/v1/tool-invocations/${encodeURIComponent(selection.invocationId)}/image-query`, { signal, cache: 'no-store' })
    if (page.project_id !== project || page.image_revision_id !== revision || page.target.object_id !== target.object_id
        || page.target.revision_id !== target.document_revision_id || page.target.source_revision_id !== target.source_revision_id
        || page.relation !== selection.relation || page.method_version !== 'nasus.link-recall.reviewed.v2'
        || page.requested_limit !== selection.limit || page.review_scope !== 'pinned_query_heads_not_live'
        || !/^sha256:[0-9a-f]{64}$/.test(page.review_scope_digest)
        || !Array.isArray(page.review_screening) || page.review_screening.length > 64
        || new Set(page.review_screening.map((item) => item.head_decision_id)).size !== page.review_screening.length
        || page.review_screening.some((item) => !item.subject_object_id || !item.head_decision_id || !item.claim_id || !item.source_image_revision_id
          || !/^sha256:[0-9a-f]{64}$/.test(item.head_decision_digest) || !['accept', 'reject', 'defer'].includes(item.decision)
          || !['rejected_same_revisions', 'identity_unresolved', 'different_endpoints', 'stale_requires_review', 'same_revisions_review_required'].includes(item.status))
        || !Number.isInteger(page.excluded.historical_review) || page.excluded.historical_review < 0
        || new Set(page.review_screening.filter((item) => ['rejected_same_revisions', 'identity_unresolved', 'different_endpoints'].includes(item.status))
          .map((item) => item.subject_object_id)).size !== page.excluded.historical_review
        || ![page.matched_count, page.pre_review_matched_count, page.eligible_count].every((count) => Number.isInteger(count) && count >= 0)
        || page.pre_review_matched_count > page.eligible_count || page.items.length !== Math.min(page.matched_count, selection.limit)
        || page.truncated !== (page.matched_count > page.items.length)
        || page.pre_review_matched_count !== page.matched_count + page.excluded.historical_review
        || page.semantic_status !== 'retrieval_only_not_implementation_or_coverage' || page.authority_status !== 'pending_confirmation'
        || page.items.some((item) => item.status !== 'retrieved_not_asserted' || item.calibrated_probability !== null
          || !['unreviewed', 'requires_revalidation', 'reviewed_not_approved'].includes(item.review_status))) {
      throw new Error('Candidate recall scope mismatch')
    }
    return page
  },
}
