import type { GenerationArchive, PlannedCoverageRow } from './testDesignGeneration'

export interface AssertionReview {
  case_id: string; row_id: string; step_index: number; oracle_digest: string
  decision: 'accept' | 'reject' | 'defer'; reason: string
}
export interface MappingQuery {
  project_id: string; generation_id: string; generation_artifact_hash: string
}
export interface MappingReview extends MappingQuery {
  expected_previous_revision_id: string | null; decision: 'review' | 'withdraw'
  mappings: AssertionReview[] | null; reason: string; policy_revision: 'nasus.test-design-mapping.v1'
}
export interface MappingRevision extends MappingQuery {
  revision_id: string; previous_revision_id: string | null; sequence: number; status: 'reviewed' | 'withdrawn'
  artifact_hash: string; request_hash: string; authority_actor: string; invocation_id: string; recorded_at: string
  mapping_schema?: 'nasus.test-design-mapping-review.v2'; plan_digest?: string; part_set_digest?: string
}
export interface MappingAssessment {
  coverage: Omit<GenerationArchive['result']['proposal']['coverage'], 'schema' | 'rows' | 'assertion_mapped_count'> & {
    schema: 'nasus.reviewed-test-design-coverage.v1'; assertion_mapped_count: number
    rows: (Omit<PlannedCoverageRow, 'assertion_mapped' | 'mapping_status'> & {
      assertion_mapped: boolean; mapping_status: 'reviewed'; accepted_case_ids: string[]; rejected_case_ids: string[]; deferred_case_ids: string[]
    })[] }
  accepted_case_ids: string[]; accepted_assertion_count: number; rejected_assertion_count: number; deferred_assertion_count: number
  mapping_complete: boolean; execution_authorized: false
}
export interface MappingArchive {
  revision: MappingRevision; request: MappingReview
  generation_pin: { generation_id: string; artifact_hash: string; context_pin: GenerationArchive['result']['context_pin']
    scope_pin: GenerationArchive['result']['scope_pin']; input_digest: string; proposal_hash: string }
  assessment: MappingAssessment | null; historical_not_live: true
  current_use: { scope_current: boolean; mapping_current: boolean; mapping_complete: boolean; execution_authorized: false }
}
export interface MappingFinalize extends MappingQuery {
  plan_digest: string; expected_previous_revision_id: string | null; part_set_digest: string
  decision: 'review'; reason: string; policy_revision: 'nasus.test-design-mapping.v2'
}
export interface MappingPlan {
  schema: 'nasus.test-design-mapping-plan.v1'; policy_revision: 'nasus.test-design-mapping-partition.v1'
  generation_pin: MappingArchive['generation_pin'] & { project_id: string }; expected_previous_revision_id: string | null
  case_count: number; assertion_count: number; part_size: 128; part_count: number; layout_digest: string
  execution_authorized: false; plan_digest: string
}
export interface MappingPartMember {
  sequence: number; part_revision_id: string; artifact_hash: string; request_hash: string; part_digest: string
}
export interface MappingPartSet {
  schema: 'nasus.test-design-mapping-part-set.v1'; plan_digest: string; authority_actor: string
  part_count: number; assertion_count: number; members_digest: string; part_set_digest: string; members: MappingPartMember[]
}
export interface PartitionedMappingArchive extends Omit<MappingArchive, 'request' | 'assessment'> {
  request: MappingFinalize; assessment: MappingAssessment; plan: MappingPlan; part_set: MappingPartSet
}
export type RecordedMappingArchive = MappingArchive | PartitionedMappingArchive
export interface MappingView extends MappingQuery {
  head: RecordedMappingArchive | null; history: MappingRevision[]; scope_current: boolean; can_review: boolean
}
