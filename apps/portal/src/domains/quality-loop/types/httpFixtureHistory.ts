export interface FixtureHistoryQuery { project_id: string; after_id: string; limit: number }
export interface FixtureHistoryItem {
  project_id: string; invocation_id: string
  tool_id: 'quality.http_fixture.authorize' | 'quality.http_fixture.execute' | 'quality.http_fixture.cancel'
  stage: 'grant' | 'execute' | 'cancel'
  status: 'pending' | 'waiting_confirmation' | 'waiting_approval' | 'running' | 'completed' | 'failed' | 'cancelled'
  request_digest: string; recipe_id: string; recipe_artifact_hash: string; run_plan_id: string; run_plan_artifact_hash: string
  case_id: string; attempt_id: string; operation: 'setup' | 'cleanup'
  original_execution_id: string | null; grant_id: string | null; grant_digest: string | null
  observation: 'original_command_metadata_not_target_observation'
  execution_authorized: false; canonical_execution_committed: false; business_coverage_verified: false; baseline_restored: false
}
export interface FixtureHistoryPage {
  schema: 'nasus.http-fixture-operation-history.v1'; request: FixtureHistoryQuery; items: FixtureHistoryItem[]
  total: number; next_after_id: string | null; source_scope_digest: string
  observation: FixtureHistoryItem['observation']
  execution_authorized: false; canonical_execution_committed: false; business_coverage_verified: false; baseline_restored: false
}
