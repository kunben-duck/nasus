import type { LinkRelation } from '../linkCandidateApi'

export interface SemanticSelection {
  project_id: string; image_revision_id: string; expected_image_hash: string; target_object_id: string
  relation: LinkRelation; subject_object_ids: string[]; model_config_id: string; recall_limit: number
  recall_invocation_id?: string
}
export interface SemanticRequest extends SemanticSelection { input_digest: string; model_config_digest: string; review_scope_digest?: string }
export interface SemanticScreeningItem {
  subject_object_id: string; head_decision_id: string; head_decision_digest: string; claim_id: string
  source_image_revision_id: string; decision: 'accept' | 'reject' | 'defer'
  status: 'rejected_same_revisions' | 'identity_unresolved' | 'different_endpoints' | 'stale_requires_review' | 'same_revisions_review_required'
  candidate_action: string
}
export interface SemanticPreview {
  request: SemanticRequest; provider: string; model_name: string; destination: string; source_binding_ids: string[]
  input_bytes: number; max_model_calls: 1; timeout_seconds: 60; max_output_tokens: 8192
  method_version: 'nasus.semantic-link-judgment.v1'; cost_estimate_available: false
  purpose: 'source_egress_for_proposed_semantic_review'
  review_screening: SemanticScreeningItem[]
}
export interface SemanticSpan {
  span_id: string; object_id: string; revision_id: string; source_revision_id: string; evidence_id: string
  relative_path: string; start_line: number; end_line: number; text_hash: string
  basis: 'source_excerpt' | 'projected_field'; role: string; field_index: number | null
}
export interface SemanticCitation { span_id: string; start: number; end: number; quote: string; quote_hash: string }
export interface SemanticJudgment {
  subject_object_id: string; subject_revision_id: string; target_object_id: string; target_revision_id: string
  relation: LinkRelation; assessment: 'supports' | 'contradicts' | 'unrelated' | 'unknown'; reason_summary: string
  evidence: SemanticCitation[]; counterevidence: SemanticCitation[]; unknowns: string[]
  oracle: { span_id: string; expected_value: string } | null
}
export interface SemanticResult {
  invocation_id: string; artifact_hash: string; request: SemanticRequest; spans: SemanticSpan[]
  evaluation: {
    input_digest: string; status: 'proposed'; semantic_kind: 'inferred'; calibrated_probability: null
    authority_status: 'pending_confirmation'; applicability: 'selected_image_only_not_verified_coverage'
    method_version: 'nasus.semantic-link-judgment.v1'; authority_kind: 'source_projection'
    authority_object_id: string; authority_revision_id: string
    judgments: SemanticJudgment[]
  }
}
export interface SemanticHistoryItem {
  invocation_id: string; request: SemanticRequest; model_name: string; recorded_at: string
  state: 'archived' | 'incomplete'; artifact_hash: string | null
}
export interface SemanticHistory {
  project_id: string; image_revision_id: string; image_artifact_hash: string; target_object_id: string
  relation: LinkRelation; items: SemanticHistoryItem[]; next_after_id: string | null
}
