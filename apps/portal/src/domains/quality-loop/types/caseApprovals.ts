import type { AutomationInputPreview } from './automationInput'

export interface CaseAdmissionSelection {
  project_id: string; mapping_revision_id: string; mapping_artifact_hash: string; case_ids: string[]
}
export type CaseAdmissionBasis = Pick<AutomationInputPreview,
  'project_id' | 'input_digest' | 'context_pin' | 'scope_pin' | 'generation_pin' | 'mapping_pin'
  | 'constraint_denominator' | 'obligation_denominator'> & {
  case_pins: { case_id: string; case_digest: string }[]
  obligation_pins: Pick<AutomationInputPreview['obligations'][number], 'row_id' | 'oracle_digest' | 'selected_case_ids'>[]
  constraints_digest: string; scope_contract_digest: string
}
export interface CaseAdmissionRevision {
  revision_id: string; project_id: string; generation_id: string; mapping_revision_id: string; cohort_id: string
  previous_revision_id: string | null; sequence: number; status: 'approved' | 'withdrawn'
  artifact_hash: string; request_hash: string; input_digest: string; case_count: number
  authority_actor: string; invocation_id: string; recorded_at: string
}
export interface CaseAdmissionPreview {
  selection: CaseAdmissionSelection; prepared: AutomationInputPreview; basis: CaseAdmissionBasis; cohort_id: string
  input_current: boolean; can_review: boolean; head: CaseAdmissionRevision | null
  head_revision_id: string | null; history_count: number; execution_authorized: false; business_coverage_verified: false
}
export interface CaseAdmissionRequest extends CaseAdmissionSelection {
  expected_input_digest: string; expected_previous_revision_id: string | null
  decision: 'approve' | 'withdraw'; reason: string; policy_revision: 'nasus.test-design-case-admission.v1'
}
