import type { GenerationArchive, GenerationPreview, GenerationRequest } from './testDesignGeneration'
import type { ObservableOracle } from './observableOracle'

export interface BatchModelBinding { config_id: string; config_digest: string; provider: string; model_name: string; base_url: string }
export interface BatchBudgetReservation {
  currency: 'USD' | 'CNY'; call_count: number; estimated_input_tokens: number; reserved_input_tokens_per_call: number
  max_output_tokens_per_call: number; reserved_tokens: number; reserved_cost_nanos: number
  count_basis: 'local_tokenizer_with_operator_framing'; cost_basis: 'operator_rate_ceiling_not_provider_invoice'
}
export interface BatchCallSpec { sequence: number; batch_digest: string; messages_hash: string; estimated_input_tokens: number }
export interface BatchReservation {
  schema_version: 'nasus.test-design-batch-reservation.v1'; project_id: string; invocation_id: string; actor_id: string
  request: GenerationRequest; model_binding: BatchModelBinding; policy: GenerationPreview['policy']; plan_digest: string
  batches: BatchCallSpec[]; reservation: BatchBudgetReservation
}
export interface NativeBatchProof {
  claim: { project_id: string; invocation_id: string; sequence: number; batch_digest: string; call_id: string; request_hash: string; reserved_at: string }
  reply: { project_id: string; invocation_id: string; sequence: number; batch_digest: string; call_id: string; response_hash: string; artifact_hash: string
    usage: { input_tokens: number; output_tokens: number; cost_nanos_at_policy_rates: number; currency: 'USD' | 'CNY'; usage_source: 'provider'; invoice_verified: false } }
  audit: { id: string; provider: string; model_name: string; request_hash: string; response_hash: string
    input_tokens: number; output_tokens: number; usage_source: 'provider'; occurred_at: string }
}
export interface GenerationBatchRecovery {
  schema_version: 'nasus.test-design-batch-recovery.v1'; project_id: string; invocation_id: string
  request_hash: string; reservation_hash: string; plan_digest: string; replies_digest: string
  replies: { sequence: number; batch_digest: string; call_id: string; request_hash: string
    reply_artifact_hash: string; response_hash: string; usage_digest: string; audit_digest: string }[]
}
export interface GenerationBatchArchive extends GenerationArchive {
  view_schema: 'nasus.test-design-result-view.v3' | 'nasus.test-design-result-view.v4'; view_hash: string
  metadata: GenerationArchive['metadata'] & { schema: 'nasus.test-design-result.v3' | 'nasus.test-design-result.v4'; call_id: null; call_ids: string[]; batch_count: number; plan_digest: string }
  result: GenerationArchive['result'] & {
    schema: 'nasus.test-design-result.v3' | 'nasus.test-design-result.v4'; actor_id: string; model_binding: BatchModelBinding; reservation: BatchReservation
    recovery_request?: GenerationBatchRecovery
    batch_plan: { schema: 'nasus.test-design-batch-plan.v1'; input_digest: string; plan_digest: string
      batches: { sequence: number; batch_digest: string; generation_input_digest: string; mandatory_constraint_ids: string[]; local_constraint_ids: string[]; global_rule_ids: string[]
        context_pin: GenerationArchive['result']['context_pin']; scope_pin: GenerationArchive['result']['scope_pin']
        obligations: { row_id: string; oracle_digest: string; oracle: ObservableOracle; constraint_ids: string[] }[] }[] }
    calls: NativeBatchProof[]; provenance: { batch_digest: string; response_hash: string; case_id_map: Record<string, string>; gap_id_map: Record<string, string> }[]
    merged_output_hash: string
  }
}
