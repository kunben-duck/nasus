import type { SemanticJudgment } from './semanticEvaluation'

export type SemanticReviewChoice = 'accept' | 'reject' | 'defer'
export interface SemanticAssertion {
  assertion_id: string; assertion_digest: string; claim_id: string; project_id: string
  image_revision_id: string; image_artifact_hash: string; evaluation_id: string; evaluation_artifact_hash: string
  input_digest: string; subject_object_id: string; subject_revision_id: string; object_id: string; object_revision_id: string
  predicate: SemanticJudgment['relation']; assessment: SemanticJudgment['assessment']
  subject_evidence_ids: string[]; object_evidence_ids: string[]; evidence_digest: string; oracle_digest: string | null
  method_version: 'nasus.semantic-link-judgment.v1'; semantic_kind: 'inferred'; status: 'proposed'
  authority_status: 'pending_confirmation'; applicability: 'selected_image_only_not_verified_coverage'; can_accept: boolean
}
export interface SemanticReviewDecision {
  decision_id: string; project_id: string; claim_id: string; assertion_id: string; assertion_digest: string
  evidence_digest: string; evaluation_id: string; image_revision_id: string; decision: SemanticReviewChoice
  reason: string; reviewer_actor: string; recorded_at: string; invocation_id: string
  previous_decision_id: string | null; sequence: number
  policy_revision: 'nasus.semantic-link-review.v1'; applicability: 'selected_image_only_not_verified_coverage'
}
export interface SemanticReviewPage {
  assertion: SemanticAssertion; policy_revision: 'nasus.semantic-link-review.v1'
  head_decision_id: string | null; head: SemanticReviewDecision | null; total: number
  items: SemanticReviewDecision[]; next_offset: number | null; publication: 'not_in_image_membership'
}
