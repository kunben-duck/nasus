import type { RunPlanLocatorView } from './runPlanLocators'

export interface LocatorRecordRequest { project_id: string; run_plan_id: string; run_plan_artifact_hash: string }
export interface LocatorRecordArchive {
  schema: 'nasus.run-plan-locator-record.v1'; project_id: string; record_id: string
  invocation_id: string; actor_id: string; recorded_at: string; request: LocatorRecordRequest
  parents: { plan_digest: string; image_revision_id: string; image_artifact_hash: string; manifest_id: string; manifest_hash: string }
  report: RunPlanLocatorView['report']
}
export type LocatorRecordMetadata = LocatorRecordRequest & LocatorRecordArchive['parents'] & {
  schema: LocatorRecordArchive['schema']; record_id: string; invocation_id: string; actor_id: string; recorded_at: string
  request_hash: string; artifact_hash: string; inventory_hash: string; report_hash: string
  summary: RunPlanLocatorView['report']['summary']; status: 'recorded'; historical_not_live: true
  source_bytes_verified: true; durable_locator_evidence_verified: true
  runtime_locators_verified: false; fixtures_verified: false; execution_authorized: false; business_coverage_verified: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface LocatorRecordView { metadata: LocatorRecordMetadata; archive: LocatorRecordArchive; historical_not_live: true }
export interface LocatorRecordAttempt {
  projectId: string; planId: string; planHash: string; requestKey: string; requestHash: string; commandId?: string
}
