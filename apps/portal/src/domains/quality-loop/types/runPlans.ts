import type { AutomationInputPreview } from './automationInput'
import type { ScriptProposal } from './automationScripts'

export interface RunPlanSources {
  project_id: string; image_revision_id: string; image_artifact_hash: string; manifest_id: string; manifest_hash: string
  source_members: { binding_id: string; source_type: string; source_revision_id: string | null; status: string }[]
}
export interface RunPlanSelection {
  project_id: string; script_revision_id: string; script_artifact_hash: string; review_revision_id: string; review_artifact_hash: string
  target_build: { code_sources: { binding_id: string; source_revision_id: string }[]; artifact_name: string; artifact_hash: string
    build_definition_hash: string; runtime: string; runtime_version: string; build_tool: string; build_tool_version: string }
  environment: { environment_id: string; kind: 'local' | 'test' | 'staging'; base_url: string; inventory_hash: string; isolation: string }
  fixtures: { case_id: string; preconditions_digest: string; data_manifest_hash: string; setup: string[]; cleanup: string[] }[]
  reason: string; policy_revision: 'nasus.run-plan.v1' | 'nasus.run-plan.v2' | 'nasus.run-plan.v3'
}
export interface RunPlanRequest extends RunPlanSelection { plan_digest: string; source_scope_digest: string }
export interface RunPlanPreview {
  request: RunPlanRequest; case_count: number; obligation_count: number; status: 'preview'
  target_verification: 'declared_not_native_verified'; execution_authorized: false; remaining_gates: string[]
}
export interface RunPlanValue {
  schema: 'nasus.run-plan.v1' | 'nasus.run-plan.v2' | 'nasus.run-plan.v3'; project_id: string; selection: RunPlanSelection; source_pin: RunPlanSources
  script_pin: { script_revision_id: string; artifact_hash: string; proposal_hash: string; input_digest: string }
  review_pin: { revision_id: string; artifact_hash: string; request_hash: string; authority_actor: string }
  prepared: AutomationInputPreview; proposal: ScriptProposal; status: 'prepared'; plan_digest: string
  target_verification: 'declared_not_native_verified'; execution_authorized: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0; remaining_gates: string[]
}
export interface RunPlanArchive {
  metadata: { project_id: string; run_plan_id: string; invocation_id: string; artifact_hash: string; request_hash: string
    plan_digest: string; status: 'prepared'; actor_id: string; recorded_at: string; context_id: string; image_revision_id: string
    manifest_id: string; script_revision_id: string; review_revision_id: string; execution_authorized: false; [key: string]: unknown }
  artifact: { schema: 'nasus.run-plan-artifact.v1' | 'nasus.run-plan-artifact.v2' | 'nasus.run-plan-artifact.v3'; project_id: string; run_plan_id: string; invocation_id: string
    actor_id: string; recorded_at: string; request: RunPlanRequest; plan: RunPlanValue }
  historical_not_live: true; current_use: { inputs_current: boolean; target_verified: false; execution_authorized: false }
}
export interface RunPlanAttempt {
  projectId: string; scriptId: string; reviewId: string; requestKey: string; requestHash: string; commandId?: string
}
export interface RunPlanFields {
  artifactName: string; artifactHash: string; definitionHash: string; runtime: string; runtimeVersion: string
  buildTool: string; buildToolVersion: string; environmentId: string; kind: 'local' | 'test' | 'staging'
  origin: string; inventoryHash: string; isolation: string; reason: string
  fixtures: Record<string, { dataHash: string; setup: string; cleanup: string }>
}
