import type { LocatorRecordAttempt } from './runPlanLocatorRecords'

export interface HttpFixtureAction { action: string; source_step_indices?: number[]; [field: string]: string | number[] | undefined }
export interface HttpFixtureManifest {
  schema: 'nasus.http-fixture-manifest.v1'; case_id: string; preconditions_digest: string
  setup: string[]; cleanup: string[]; setup_steps: HttpFixtureAction[]; cleanup_groups: Record<string, HttpFixtureAction[]>
}
export interface FixtureRecipeRequest {
  project_id: string; run_plan_id: string; run_plan_artifact_hash: string; manifest: HttpFixtureManifest
}
export interface FixtureRecipeArchive {
  schema: 'nasus.http-fixture-recipe.v1'; project_id: string; record_id: string; invocation_id: string
  actor_id: string; recorded_at: string; request: FixtureRecipeRequest; fixture_digest: string
  parents: { plan_digest: string; image_revision_id: string; image_artifact_hash: string; manifest_id: string; manifest_hash: string }
}
export type FixtureRecipeMetadata = FixtureRecipeArchive['parents'] & {
  schema: FixtureRecipeArchive['schema']; project_id: string; record_id: string; invocation_id: string
  actor_id: string; recorded_at: string; run_plan_id: string; run_plan_artifact_hash: string
  case_id: string; data_manifest_hash: string; fixture_digest: string; request_hash: string; artifact_hash: string
  status: 'recorded'; historical_not_live: true; recipe_bytes_verified: true; fixtures_verified: false
  execution_authorized: false; canonical_execution_committed: false; business_coverage_verified: false; baseline_restored: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface FixtureRecipeView { metadata: FixtureRecipeMetadata; archive: FixtureRecipeArchive; historical_not_live: true }
export type FixtureRecipeAttempt = LocatorRecordAttempt
