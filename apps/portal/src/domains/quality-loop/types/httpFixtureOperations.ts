export type FixtureOperation = 'setup' | 'cleanup'
export type FixtureCommandStage = 'grant' | 'execute' | 'cancel'
export interface FixtureCommandAttempt { requestKey: string; requestHash: string; commandId?: string }
export interface FixtureOperationAttempt {
  projectId: string; planId: string; planHash: string; recipeId: string; recipeHash: string
  environmentCommandId: string; attemptId: string; operation: FixtureOperation; timeoutMs: number
  grant: FixtureCommandAttempt; execute?: FixtureCommandAttempt; cancel?: FixtureCommandAttempt
}
export interface FixtureGrantRequest {
  project_id: string; recipe_id: string; recipe_artifact_hash: string; attempt_id: string
  operation: FixtureOperation; timeout_ms: number; policy_revision: 'nasus.http-fixture-grant.v2'
  environment_record_id: string; environment_record_artifact_hash: string
}
export interface FixtureGrantScope {
  project_id: string; attempt_id: string; case_id: string; parent_digest: string; data_manifest_hash: string
  environment_id: string; artifact_hash: string; inventory_hash: string; timeout_ms: number
}
export interface FixtureGrantMetadata extends Omit<FixtureGrantRequest, 'policy_revision'> {
  policy_revision: FixtureGrantRequest['policy_revision']; schema: FixtureGrantRequest['policy_revision']
  record_id: string; invocation_id: string; actor_id: string; recorded_at: string; expires_at: string
  scope: FixtureGrantScope; source_scope_digest: string; request_hash: string; scope_digest: string; grant_digest: string
  native_environment: { record_id: string; artifact_hash: string; inventory_hash: string; operator_policy_digest: string }
  status: 'issued'; historical_not_live: true; scope_permission_recorded: true
  execution_authorized: false; canonical_execution_committed: false; fixtures_verified: false
  business_coverage_verified: false; baseline_restored: false; automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface FixtureGrantView { metadata: FixtureGrantMetadata; historical_not_live: true }
export interface FixtureExecutionSelection { project_id: string; grant_id: string; grant_digest: string; operation: FixtureOperation }
export interface FixtureCancelSelection { project_id: string; invocation_id: string }
export type FixturePhase = { phase: string; claim_id: string } & (
  { state: 'not_dispatched' } | { state: 'outcome_unknown'; dispatch_digest: string }
  | { state: 'observed'; dispatch_digest: string; result_status: 'passed' | 'failed' | 'error' | 'timed_out'; result_digest: string })
export interface FixtureJobView {
  schema: 'nasus.http-fixture-job.v1' | 'nasus.http-fixture-job.v2'; project_id: string; invocation_id: string
  request_digest: string; selection: FixtureExecutionSelection; status: 'running' | 'completed' | 'failed' | 'cancelled'
  intent_digest: string | null; phases: FixturePhase[]; preparation_digest?: string
  phase?: 'preparing' | 'preparation_failed' | 'preparation_cancelled'; target_observation_verified?: false
  cancellation_requested: boolean; cancellation_delivered: boolean; execution_authorized: false
  canonical_execution_committed: false; business_coverage_verified: false; baseline_restored: false
}
