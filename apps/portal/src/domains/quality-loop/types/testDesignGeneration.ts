import type { ObservableOracle } from './observableOracle'
import type { BatchBudgetReservation, GenerationBatchRecovery } from './generationBatchResult'

export interface GenerationBudget {
  currency: 'USD' | 'CNY'; max_calls: number; max_reserved_tokens: number; max_reserved_cost_nanos: number
  max_input_tokens_per_call: number; max_output_tokens_per_call: number
}
export interface GenerationSelection {
  project_id: string; scope_revision_id: string; scope_artifact_hash: string; model_config_id: string; budget: GenerationBudget
}
export interface GenerationRequest {
  project_id: string; scope_revision_id: string; scope_artifact_hash: string; input_digest: string
  model_config_id: string; model_config_digest: string
  execution: { policy_digest: string; plan_digest: string; source_binding_ids: string[]; source_scope_digest: string
    budget: GenerationBudget; purpose: 'draft_test_design_source_egress' }
}
export interface GenerationPreview {
  request: GenerationRequest; provider: string; model_name: string; destination: string
  policy: { config_id: string; provider: string; model_name: string; base_url: string; currency: 'USD' | 'CNY'
    context_tokens: number; max_output_tokens: number; input_nanos_per_token: number; output_nanos_per_token: number
    tokenizer_kind: 'tiktoken' | 'huggingface_json'; tokenizer_id: string; tokenizer_digest: string; framing_tokens: number
    policy_id: string; revision: string }
  reservation: { currency: 'USD' | 'CNY'; call_count: number; estimated_input_tokens: number; reserved_input_tokens_per_call: number
    max_output_tokens_per_call: number; reserved_tokens: number; reserved_cost_nanos: number
    count_basis: 'local_tokenizer_with_operator_framing'; cost_basis: 'operator_rate_ceiling_not_provider_invoice' }
  input_bytes: number; timeout_seconds: 120; call_count: number; batching: 'one_complete_input_no_truncation' | 'complete_constraint_batches_no_truncation'
  batch_planning?: GenerationBatchPlanningPreview
  generation_authorized: false; execution_authorized: false; remaining_gates: string[]
}
export interface GenerationBatchPlanningPreview {
  schema: 'nasus.test-design-batch-planning.v1'; selection: GenerationSelection
  model_binding: { config_id: string; config_digest: string; provider: string; model_name: string; base_url: string }
  policy: GenerationPreview['policy']; source_binding_ids: string[]; source_scope_digest: string
  plan_digest: string; reservation: BatchBudgetReservation; messages_hashes: string[]; planning_digest: string; input_digest: string
  batches: { batch_digest: string; sequence: number; owned_obligation_count: number; local_constraint_count: number
    global_rule_count: number; selected_fact_count: number; estimated_input_tokens: number }[]
  generation_authorized: false; execution_authorized: false; remaining_gates: string[]
}
export interface GenerationBatchProgress {
  schema: 'nasus.test-design-batch-progress.v1'; plan_digest: string; call_count: number; claimed_calls: number; archived_calls: number
  unknown_calls: number; unstarted_calls: number; known_input_tokens: number; known_output_tokens: number
  known_cost_nanos_at_policy_rates: number; reservation: BatchBudgetReservation
  reservation_released: false; invoice_verified: false; execution_authorized: false
}
export interface GenerationSingleRecovery {
  project_id: string; invocation_id: string; request_hash: string; reply_artifact_hash: string; response_hash: string
}
export type GenerationRecovery = GenerationSingleRecovery | GenerationBatchRecovery
export interface GenerationHistoryRequest {
  project_id: string; scope_revision_id: string; scope_artifact_hash: string; after_id: string; limit: number
}
export interface GenerationHistoryItem {
  invocation_id: string; source_invocation_id: string
  tool_id: 'quality.test_design.generate' | 'quality.test_design.recover'
  status: 'running' | 'completed' | 'failed' | 'cancelled'
}
export interface GenerationHistoryPage {
  request: GenerationHistoryRequest; items: GenerationHistoryItem[]; next_after_id: string | null
  has_running: boolean; generation_authorized: false; execution_authorized: false
}
export interface GenerationJob {
  project_id: string; invocation_id: string; source_invocation_id: string; scope_revision_id: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'; call_reserved: boolean; reply_archived: boolean
  provider_outcome_unknown: boolean; generation_id: string | null; recovery_request: GenerationRecovery | null; execution_authorized: false
  batch_progress?: GenerationBatchProgress
}
export interface PlannedCase {
  case_id: string; title: string; preconditions: string[]; inputs: string[]; steps: string[]
  assertions: { row_id: string; oracle_digest: string; oracle: ObservableOracle; step_index: number }[]
  global_constraint_ids: string[]; supporting_fact_ids: string[]; reused_case_ids: string[]
}
export interface PlannedCoverageRow {
  row_id: string; kind: string; constraint_ids: string[]; oracle_digest: string; planned_case_ids: string[]
  proposed_assertion_case_ids: string[]; gap_ids: string[]; planned: boolean; assertion_mapped: false
  automated: false; executed_on_target: false; passed: false; unknown: true; mapping_status: 'pending_independent_review'
}
export interface GenerationArchive {
  metadata: { project_id: string; generation_id: string; scope_revision_id: string; invocation_id: string; call_id: string | null
    status: 'draft'; artifact_hash: string; case_count: number; gap_count: number; recovery_invocation_id?: string
    schema?: 'nasus.test-design-result.v3' | 'nasus.test-design-result.v4'; call_ids?: string[]; batch_count?: number; plan_digest?: string }
  result: { schema: 'nasus.test-design-result.v1' | 'nasus.test-design-result.v2' | 'nasus.test-design-result.v3' | 'nasus.test-design-result.v4'; project_id: string; generation_id: string
    invocation_id: string; recovery_invocation_id?: string; request: GenerationRequest; status: 'draft'
    context_pin: { context_id: string; artifact_hash: string; input_digest: string; image_revision_id: string; image_artifact_hash: string }
    scope_pin: { revision_id: string; artifact_hash: string; request_hash: string }
    mapping_status: 'pending_independent_review'; execution_authorized: false
    proposal: { cases: PlannedCase[]; gaps: { gap_id: string; row_ids: string[]; description: string }[]
      coverage: { schema: 'nasus.test-design-coverage.v1'; input_digest: string; rows: PlannedCoverageRow[]
        context_pin: GenerationArchive['result']['context_pin']; scope_pin: GenerationArchive['result']['scope_pin']
        constraint_denominator: number; obligation_denominator: number; planned_constraint_count: number; planned_obligation_count: number
        gap_obligation_count: number; unknown_count: number; assertion_mapped_count: 0; automated_count: 0
        executed_on_target_count: 0; passed_count: 0; execution_authorized: false } } }
  historical_not_live: true; current_use: { scope_current: boolean; mapping_approved: false; execution_authorized: false }
  view_schema?: 'nasus.test-design-result-view.v3' | 'nasus.test-design-result-view.v4'; view_hash?: string
}
