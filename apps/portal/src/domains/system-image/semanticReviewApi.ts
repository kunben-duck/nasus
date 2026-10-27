import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { SemanticJudgment, SemanticResult } from './types/semanticEvaluation'
import type { SemanticReviewChoice, SemanticReviewDecision, SemanticReviewPage } from './types/semanticReview'

const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
const policy = 'nasus.semantic-link-review.v1'
const applicability = 'selected_image_only_not_verified_coverage'
export class StaleSemanticReview extends Error {}

export function verifySemanticReviews(page: SemanticReviewPage, result: SemanticResult, subject: SemanticJudgment, offset: number, head?: string) {
  const a = page.assertion
  const selection = result.request
  const evidenceIds = (object: string) => [...new Set(result.spans.filter((span) => span.object_id === object).map((span) => span.evidence_id))].sort()
  if (a.project_id !== selection.project_id || a.image_revision_id !== selection.image_revision_id || a.image_artifact_hash !== selection.expected_image_hash
      || a.evaluation_id !== result.invocation_id || a.evaluation_artifact_hash !== result.artifact_hash || a.input_digest !== selection.input_digest
      || a.subject_object_id !== subject.subject_object_id || a.subject_revision_id !== subject.subject_revision_id
      || a.object_id !== subject.target_object_id || a.object_revision_id !== subject.target_revision_id
      || a.predicate !== subject.relation || a.assessment !== subject.assessment || !digest(a.assertion_digest) || !digest(a.evidence_digest)
      || a.assertion_id !== `sa_${a.assertion_digest.slice(7)}` || !/^sc_[0-9a-f]{64}$/.test(a.claim_id)
      || JSON.stringify(a.subject_evidence_ids) !== JSON.stringify(evidenceIds(a.subject_object_id))
      || JSON.stringify(a.object_evidence_ids) !== JSON.stringify(evidenceIds(a.object_id))
      || (subject.oracle ? !a.oracle_digest || !digest(a.oracle_digest) : a.oracle_digest !== null)
      || a.method_version !== 'nasus.semantic-link-judgment.v1' || a.semantic_kind !== 'inferred' || a.status !== 'proposed'
      || a.authority_status !== 'pending_confirmation' || a.applicability !== applicability
      || a.can_accept !== (subject.assessment === 'supports' && (subject.relation !== 'asserts' || !!subject.oracle))
      || page.policy_revision !== policy || page.publication !== 'not_in_image_membership'
      || !Number.isInteger(page.total) || page.total < offset || page.total > 1000 || page.items.length > 20
      || page.items.length > page.total - offset || (page.total > offset && page.items.length === 0)
      || page.next_offset !== (offset + page.items.length < page.total ? offset + page.items.length : null)
      || (head !== undefined && page.head_decision_id !== (head || null))) throw new Error('Semantic review scope mismatch')
  function verifyDecision(d: SemanticReviewDecision) {
    if (d.project_id !== a.project_id || d.claim_id !== a.claim_id || d.image_revision_id !== a.image_revision_id
        || d.policy_revision !== policy || d.applicability !== applicability || !['accept', 'reject', 'defer'].includes(d.decision)
        || !digest(d.assertion_digest) || !digest(d.evidence_digest) || d.assertion_id !== `sa_${d.assertion_digest.slice(7)}`
        || !d.decision_id || !d.evaluation_id || !d.reviewer_actor || !d.reason.trim() || d.reason.length > 2000
        || !Number.isInteger(d.sequence) || d.sequence < 1 || d.sequence > page.total
        || (d.sequence === 1) !== (d.previous_decision_id === null)) throw new Error('Semantic decision mismatch')
  }
  if (page.total === 0) {
    if (page.head !== null || page.head_decision_id !== null) throw new Error('Unexpected semantic head')
  } else {
    if (!page.head || page.head.decision_id !== page.head_decision_id || page.head.sequence !== page.total) throw new Error('Semantic head missing')
    verifyDecision(page.head)
  }
  page.items.forEach((d, index) => {
    verifyDecision(d)
    if (d.sequence !== offset + index + 1 || (index > 0 && d.previous_decision_id !== page.items[index - 1].decision_id)
        || (d.sequence === page.total && JSON.stringify(d) !== JSON.stringify(page.head))) throw new Error('Semantic history mismatch')
  })
  return page
}

export const semanticReviewApi = {
  async history(result: SemanticResult, subject: SemanticJudgment, offset: number, signal: AbortSignal, head?: string) {
    const params = new URLSearchParams({ offset: String(offset), limit: '20' })
    if (head !== undefined) params.set('through_decision_id', head)
    const root = `/v1/projects/${encodeURIComponent(result.request.project_id)}/system-image/semantic-evaluations/${encodeURIComponent(result.invocation_id)}`
    const page = await request<SemanticReviewPage>(`${root}/subjects/${encodeURIComponent(subject.subject_object_id)}/reviews?${params}`, { signal, cache: 'no-store' })
    return verifySemanticReviews(page, result, subject, offset, head)
  },
  async record(page: SemanticReviewPage, decision: SemanticReviewChoice, reason: string, attempt: string) {
    const a = page.assertion
    if (!reason.trim() || reason.length > 2000 || (decision === 'accept' && !a.can_accept)) throw new Error('Invalid semantic decision')
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.links.review_semantic', idempotency_key: attempt,
      input: { project_id: a.project_id, evaluation_id: a.evaluation_id, subject_object_id: a.subject_object_id,
        assertion_id: a.assertion_id, assertion_digest: a.assertion_digest, evidence_digest: a.evidence_digest,
        expected_previous_decision_id: page.head_decision_id, policy_revision: page.policy_revision, decision, reason } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Explicit review confirmation required')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.result?.followup_reason === 'stale_semantic_decision') throw new StaleSemanticReview('Review changed')
    if (done.status !== 'completed' || !done.result?.object_refs.some((ref) => ref.startsWith('semantic_link_decision:'))) {
      throw new Error('Semantic decision was not acknowledged')
    }
    return done.id
  },
}
