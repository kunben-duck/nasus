import type { NativeBuildReceipt, NativeBuildView } from './runPlanBuilds'

export interface NativeBuildSelection {
  project_id: string; image_revision_id: string; image_artifact_hash: string; binding_id: string; source_revision_id: string
  artifact_path: string; expected_artifact_hash: string | null
}
export interface NativeBuildCommand extends NativeBuildSelection {
  request_digest: string; operator_policy_digest: string; source_scope_digest: string
}
export interface NativeBuildPolicy {
  adapter: 'nasus.offline-java21-maven3911.v1'; image_id: string; cache_identity_hash: string; timeout_seconds: number
  network: 'none'; cache_access: 'read_only'; cache_contents_attested: false
}
export interface NativeBuildPreview {
  request: NativeBuildCommand; source: { pin: NativeBuildReceipt['source']['pin']; file_count: number; byte_count: number }
  operator_policy: NativeBuildPolicy; status: 'preview'; source_execution_started: false; execution_authorized: false; remaining_gates: string[]
}
export interface NativeBuildPendingView {
  project_id: string; invocation_id: string; status: string; metadata: null; call_reserved: boolean; outcome_unknown: boolean
  worker: 'none' | 'active' | 'expired'; cleanup_confirmed: false; execution_authorized: false
}
export type NativeBuildJobView = NativeBuildView | NativeBuildPendingView
export interface NativeBuildAttempt {
  projectId: string; imageId: string; imageHash: string; requestKey: string; requestHash: string; commandId?: string
}
