import type { FixtureHistoryItem } from './httpFixtureHistory'
import type { FixtureJobView } from './httpFixtureOperations'

export interface FixtureOriginalObservation {
  schema: 'nasus.http-fixture-original-observation.v1'
  selected: FixtureHistoryItem
  execution: FixtureHistoryItem | null
  expected_phases: { phase: string; claim_id: string }[]
  job: FixtureJobView | null
  state: 'not_execution' | 'not_confirmed' | 'preparing' | 'preparation_failed' | 'preparation_cancelled'
    | 'not_dispatched' | 'outcome_unknown' | 'observed' | 'partially_observed'
  source_scope_digest: string
  observation: 'original_persisted_journal_not_live_target'
  execution_authorized: false
  canonical_execution_committed: false
  business_coverage_verified: false
  baseline_restored: false
}
