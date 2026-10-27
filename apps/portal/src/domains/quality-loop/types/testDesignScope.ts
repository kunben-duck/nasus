import type { ObservableOracle } from './observableOracle'

export type ScopeDimension = 'risks' | 'permissions' | 'transitions' | 'invariants'
export interface ScopeObligation {
  obligation_id: string; constraint_ids: string[]; evidence_ids: string[]; oracle: ObservableOracle
  boundary?: string; actor?: string; operation?: string; resource?: string; expected?: 'allowed' | 'denied' | ''
  from_state?: string; event?: string; to_state?: string; invariant?: string
}
export interface ScopeAssessment { applicability: 'applicable' | 'not_applicable' | ''; rationale: string; items: ScopeObligation[] }
export interface ScopeGap { id: string; constraint_ids: string[]; description: string }
export interface ScopeConflict extends ScopeGap { resolution: string | null }
export interface ScopeExample {
  constraint_id: string; positive: ObservableOracle; negative: ObservableOracle | null
  negative_not_applicable_reason: string | null; negative_gap_id: string | null
}
export interface TestDesignContract {
  authority_basis: 'user_confirmed_test_design_scope'
  risks: ScopeAssessment; permissions: ScopeAssessment; transitions: ScopeAssessment; invariants: ScopeAssessment
  examples: ScopeExample[]; reused_case_ids: string[]; reuse_assessment: string
  conflicts: ScopeConflict[]; conflict_assessment: string; gaps: ScopeGap[]
}
export interface ScopeSelection { project_id: string; context_id: string; context_artifact_hash: string }
export interface ScopeReview extends ScopeSelection {
  expected_previous_revision_id: string | null; decision: 'approve' | 'withdraw'; contract: TestDesignContract | null
  reason: string; policy_revision: 'nasus.test-design-scope.v1'
}
export interface ScopeRevision extends ScopeSelection {
  revision_id: string; scope_id: string; previous_revision_id: string | null; sequence: number
  status: 'approved' | 'withdrawn'; artifact_hash: string; request_hash: string
  authority_actor: string; invocation_id: string; recorded_at: string
}
export interface ScopeArchive {
  revision: ScopeRevision; request: ScopeReview
  context_pin: { context_id: string; artifact_hash: string; input_digest: string; image_revision_id: string; image_artifact_hash: string }
  assessment: { constraint_ids: string[]; obligation_ids: string[]; blockers: string[]; scope_complete: boolean
    generation_authorized: false; use_policy: 'reviewed_scope_only_requires_separate_generation_preflight' } | null
  historical_not_live: true
  current_use: { scope_current: boolean; scope_complete: boolean; generation_authorized: false }
}
export interface ScopeView {
  scope_id: string; context_id: string; context_artifact_hash: string; head: ScopeArchive | null
  history: ScopeRevision[]; context_current_use: { stale: boolean; generation_authorized: false; reason: string }; can_review: boolean
}
