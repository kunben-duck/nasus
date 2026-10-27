import type { RunPlanSources } from './runPlans'

export interface NativeBuildReference { invocation_id: string; build_id: string; artifact_hash: string; receipt_digest: string }
export interface NativeBuildReceipt {
  schema: 'nasus.native-build.v1'; adapter: 'nasus.offline-java21-maven3911.v1'; request_digest: string
  source: { pin: Omit<RunPlanSources, 'source_members'> & { binding_id: string; source_revision_id: string; [key: string]: unknown }
    files: { path: string; content_hash: string; byte_count: number }[]; file_mode_attested: false }
  artifact: { path: string; content_hash: string; byte_count: number }
  toolchain: { java: '21'; maven: '3.9.11'; network: 'none'; dependency_cache: 'operator_read_only'; [key: string]: unknown }
  native_build_verified: true; execution_authorized: false; executed_on_target_count: 0; passed_count: 0
  reproducible_build_verified: false; dependency_supply_chain_verified: false; [key: string]: unknown
}
export interface NativeBuildView {
  project_id: string; invocation_id: string; status: string; metadata: NativeBuildReference & {
    project_id: string; request_digest: string; artifact: NativeBuildReceipt['artifact']; execution_authorized: false; [key: string]: unknown }
  receipt: NativeBuildReceipt; execution_authorized: false; historical_not_live: true
}
export interface RunPlanBuildSelection {
  project_id: string; run_plan_id: string; run_plan_artifact_hash: string; native_builds: NativeBuildReference[]
  target_build_invocation_id: string; reason: string; policy_revision: 'nasus.run-plan-build.v1'
}
export interface RunPlanBuildRequest extends RunPlanBuildSelection { binding_digest: string; source_scope_digest: string }
export interface RunPlanBuildPreview {
  request: RunPlanBuildRequest; status: 'preview'; code_source_count: number; native_build_source_attested: true
  target_artifact_hash: string; execution_authorized: false; remaining_gates: string[]
}
export interface RunPlanBuildValue {
  schema: 'nasus.run-plan-build.v1'; project_id: string; selection: RunPlanBuildSelection
  run_plan_id: string; run_plan_artifact_hash: string; plan_digest: string; source_pin: Omit<RunPlanSources, 'source_members'>
  builds: (NativeBuildReference & { source_pin: NativeBuildReceipt['source']['pin']; request_digest: string; source_files_digest: string
    build_definition_hash: string; artifact: NativeBuildReceipt['artifact']; toolchain: NativeBuildReceipt['toolchain'] })[]
  target_build_invocation_id: string; target_artifact_hash: string; native_build_source_attested: true; source_file_modes_attested: false
  execution_authorized: false; automated_count: 0; executed_on_target_count: 0; passed_count: 0
  reproducible_build_verified: false; dependency_supply_chain_verified: false; remaining_gates: string[]; binding_digest: string
}
export interface RunPlanBuildArchive {
  metadata: { project_id: string; binding_id: string; invocation_id: string; actor_id: string; recorded_at: string; artifact_hash: string
    request_hash: string; binding_digest: string; run_plan_id: string; run_plan_artifact_hash: string; plan_digest: string
    image_revision_id: string; manifest_id: string; target_artifact_hash: string; [key: string]: unknown }
  artifact: { schema: 'nasus.run-plan-build-artifact.v1'; project_id: string; binding_id: string; invocation_id: string; actor_id: string
    recorded_at: string; request: RunPlanBuildRequest; binding: RunPlanBuildValue }
  historical_not_live: true; current_use: { inputs_current: boolean; native_build_source_attested: true
    environment_verified: false; fixtures_verified: false; execution_authorized: false }
}
export interface RunPlanBuildAttempt {
  projectId: string; planId: string; planHash: string; requestKey: string; requestHash: string; commandId?: string
}
