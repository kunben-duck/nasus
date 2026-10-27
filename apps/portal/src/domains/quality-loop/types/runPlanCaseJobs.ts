import type { ToolInvocation } from '../../platform/types'

export interface CaseExecutionSelection {
  project_id: string; run_id: string; run_plan_id: string; run_plan_artifact_hash: string; plan_digest: string
  timeout_ms: number; build_binding_id: string; build_binding_artifact_hash: string
  environment_record_id: string; environment_record_artifact_hash: string
  locator_record_id: string; locator_record_artifact_hash: string
  fixture_setups: { case_id: string; invocation_id: string }[]
}
export interface CaseExecutionFields {
  runId: string; environmentCommandId: string; locatorCommandId: string; timeoutMs: number
  setups: { caseId: string; commandId: string }[]
}
export interface CaseCommandAttempt { requestKey: string; requestHash: string; commandId?: string }
export interface CaseExecutionAttempt {
  projectId: string; planId: string; planHash: string; fields: CaseExecutionFields
  input: CaseExecutionSelection; execute: CaseCommandAttempt; cancel?: CaseCommandAttempt
}
export type CaseCommandStage = 'execute' | 'cancel'
export type CaseObservedStatus = 'passed' | 'failed' | 'error' | 'timed_out'
export interface CaseExecutionRow {
  ordinal: number; case_id: string; case_digest: string; command_digest: string; claim_id: string
  status: CaseObservedStatus | 'outcome_unknown' | 'not_dispatched'; observation_digest: string | null
}
export interface CaseExecutionState {
  schema: 'nasus.run-plan-case-state.v1' | 'nasus.run-plan-case-state.v2'; project_id: string; run_id: string; invocation_id: string; scope_digest: string
  fixture_scope_digest?: string
  fixture_input_pins?: { case_id: string; capture_set_digest: string; fixture_input_digest: string }[]
  cases: CaseExecutionRow[]; state: 'observed' | 'outcome_unknown' | 'cancelled' | 'partially_observed' | 'not_dispatched'
  cancelled: boolean; case_count: number; observed_case_count: number; outcome_unknown_case_count: number; not_dispatched_case_count: number
  business_coverage_verified: false; canonical_execution_committed: false; automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface CaseExecutionHistory {
  project_id: string; invocation_id: string; run_id: string; status: ToolInvocation['status']; bound: boolean
  history: { state: CaseExecutionState; observations: Record<string, unknown>[]; historical_not_live: true } | null
  historical_not_live: true; business_coverage_verified: false; canonical_execution_committed: false
}
