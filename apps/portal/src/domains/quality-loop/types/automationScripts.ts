import type { AutomationInputPreview } from './automationInput'
import type { GenerationBudget, GenerationPreview } from './testDesignGeneration'

export interface ScriptHistoryRequest {
  project_id: string; mapping_revision_id: string; mapping_artifact_hash: string; after_id: string; limit: number
}
export interface ScriptHistoryItem {
  invocation_id: string; status: 'running' | 'completed' | 'failed' | 'cancelled'
  call_reserved: boolean; reply_archived: boolean; provider_outcome_unknown: boolean
  script_revision_id: string | null; artifact_hash: string | null
}
export interface ScriptHistoryPage {
  request: ScriptHistoryRequest; items: ScriptHistoryItem[]; next_after_id: string | null
  generation_authorized: false; execution_authorized: false
}
export interface ScriptSelection {
  project_id: string; mapping_revision_id: string; mapping_artifact_hash: string; case_ids: string[]
  model_config_id: string; budget: GenerationBudget
  case_approval_revision_id: string; case_approval_artifact_hash: string
  http_protocol?: 'nasus.runner-http-execution.v2' | 'nasus.runner-http-execution.v3'
}
export interface ScriptRequest extends Omit<ScriptSelection, 'case_approval_revision_id' | 'case_approval_artifact_hash'> {
  case_approval_revision_id?: string; case_approval_artifact_hash?: string
  input_digest: string; model_config_digest: string
  execution: Omit<GenerationPreview['request']['execution'], 'purpose'> & { purpose: 'draft_automation_source_egress' }
}
export interface ScriptPreview extends Omit<GenerationPreview, 'request' | 'batching' | 'batch_planning'> { request: ScriptRequest }
export type ScriptAction = { action: string; source_step_indices: number[]; [field: string]: string | number[] }
export interface DraftScript {
  case_id: string; case_digest: string; kind: 'browser' | 'http'; actions: ScriptAction[]
  assertions: { row_id: string; oracle_digest: string; oracle: AutomationInputPreview['cases'][number]['assertions'][number]['oracle']
    source_step_index: number; action_index: number }[]
}
export interface ScriptProposal {
  schema: 'nasus.automation-script-proposal.v1' | 'nasus.automation-script-proposal.v2' | 'nasus.automation-script-proposal.v3'
  http_protocol?: 'nasus.runner-http-execution.v2' | 'nasus.runner-http-execution.v3'; input_digest: string; scripts: DraftScript[]
  gaps: { case_id: string; case_digest: string; description: string }[]; case_count: number; script_count: number; gap_count: number
  status: 'draft'; review_status: 'pending_independent_review'; execution_authorized: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0; remaining_gates: string[]
}
export interface ScriptArchive {
  metadata: { project_id: string; script_revision_id: string; invocation_id: string; call_id: string; response_hash: string
    status: 'draft'; artifact_hash: string; input_digest: string; mapping_revision_id: string; mapping_artifact_hash: string
    script_count: number; gap_count: number; execution_authorized: false }
  result: { schema: 'nasus.automation-script-result.v1'; project_id: string; script_revision_id: string; invocation_id: string
    actor_id: string; call_id: string; response_hash: string; request: ScriptRequest; model_binding: {
      config_id: string; config_digest: string; provider: string; model_name: string; base_url: string; [field: string]: unknown }
    prepared: AutomationInputPreview; raw_output: string; proposal: ScriptProposal; status: 'draft' }
  historical_not_live: true; current_use: { input_current: boolean; execution_authorized: false }
}
export type ScriptDecision = 'accept' | 'reject' | 'defer'
export interface ScriptActionDecision { case_id: string; action_index: number; action_digest: string; decision: ScriptDecision; reason: string }
export interface ScriptOracleDecision { case_id: string; row_id: string; action_index: number; source_step_index: number
  oracle_digest: string; decision: ScriptDecision; reason: string }
export interface ScriptReviewRequest {
  project_id: string; script_revision_id: string; script_artifact_hash: string; expected_previous_revision_id: string | null
  decision: 'review' | 'withdraw'; actions: ScriptActionDecision[] | null; assertions: ScriptOracleDecision[] | null
  reason: string; policy_revision: 'nasus.automation-script-review.v1'
}
export interface ScriptReviewAssessment {
  review_complete: boolean; reviewed_action_count: number; reviewed_oracle_count: number; accepted_count: number
  rejected_count: number; deferred_count: number; gap_count: number; automated_count: 0; executed_on_target_count: 0
  passed_count: 0; execution_authorized: false; remaining_gates: string[]
}
export interface ScriptReviewRevision {
  revision_id: string; project_id: string; script_revision_id: string; sequence: number; previous_revision_id: string | null
  artifact_hash: string; script_artifact_hash: string; request_hash: string; status: 'reviewed' | 'withdrawn'; authority_actor: string
  invocation_id: string; recorded_at: string
}
export interface ScriptReviewArchive {
  revision: ScriptReviewRevision; request: ScriptReviewRequest; assessment: ScriptReviewAssessment | null
  script_pin: Record<string, unknown>
}
export interface ScriptReviewView {
  project_id: string; script_revision_id: string; script_artifact_hash: string; script_pin: Record<string, unknown>
  head: ScriptReviewArchive | null; history: ScriptReviewRevision[]; input_current: boolean; can_review: boolean; execution_authorized: false
}
