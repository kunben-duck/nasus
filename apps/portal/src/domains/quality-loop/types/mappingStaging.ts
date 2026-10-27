import type { AssertionReview, MappingFinalize, MappingPlan, MappingQuery, MappingPartSet } from './testDesignMapping'
import type { MappingPair } from '../testDesignMappingPartitions'

export interface MappingPart {
  schema: 'nasus.test-design-mapping-part.v1'; sequence: number; part_digest: string; plan_digest: string
  assertions: MappingPair[]; execution_authorized: false
}
export interface MappingWorkspace {
  plan: MappingPlan; partDigests: string[]; actorId: string; scopeCurrent: boolean
}
export interface MappingPartStage extends MappingQuery {
  plan_digest: string; expected_previous_revision_id: string | null; sequence: number; part_digest: string
  expected_previous_part_revision_id: string | null; decisions: AssertionReview[]
  policy_revision: 'nasus.test-design-mapping-staging.v1'
}
export interface StagedPartRevision extends MappingQuery {
  part_revision_id: string; plan_digest: string; sequence: number; part_digest: string
  expected_previous_revision_id: string | null; expected_previous_part_revision_id: string | null
  revision_sequence: number; artifact_hash: string; request_hash: string; authority_actor: string
  invocation_id: string; recorded_at: string; assertion_mapped: false; execution_authorized: false
}
export interface StagedPartHead extends MappingQuery {
  plan_digest: string; sequence: number; authority_actor: string; head: StagedPartRevision | null
  history: StagedPartRevision[]; history_count: number; history_truncated: boolean; scope_current: boolean
  assertion_mapped: false; review_authorized: false; execution_authorized: false
}
export interface StagedPartArchive {
  revision: StagedPartRevision; request: MappingPartStage; plan: MappingPlan; historical_not_live: true
  current_use: { scope_current: boolean; part_current: boolean; assertion_mapped: false; review_authorized: false; execution_authorized: false }
}
export interface MappingPartView {
  part: MappingPart; head: StagedPartHead; archive: StagedPartArchive | null
}
export interface MappingFinalPreview extends MappingQuery {
  plan_digest: string; expected_previous_revision_id: string | null; authority_actor: string
  part_count: number; saved_part_count: number; assertion_count: number; part_set: Omit<MappingPartSet, 'members'> | null
  ready_for_confirmation: boolean; scope_current: boolean; review_authorized: false; execution_authorized: false
}
export type MappingPartCommand = MappingPartStage | MappingFinalize
