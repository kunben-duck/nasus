import type { AgentGoal } from '../../agent/types'
import type { ToolInvocation } from '../../platform/types/tool'

export interface BuildCompletionInput {
  project_id: string
  investigation_revision_id: string
  investigation_revision_hash: string
  expected_goal: AgentGoal
  analyses: []
  analysis_policy: 'committed_build'
}

export interface BuildCompletionPointer { requestKey: string; invocationId: string | null }

export interface BuildCompletionReceipt {
  kind: 'build_completion'
  project_id: string
  investigation_revision_id: string
  investigation_revision_hash: string
  request_hash: string
  report_hash: string
}

export interface BuildCompletionReport {
  schema: 'nasus.image-build-completion.v2'
  project_id: string
  plan_digest: string
  image_revision_id: string
  image_artifact_hash: string
  source_manifest_id: string
  source_manifest_hash: string
  investigation_revision_id: string
  investigation_revision_hash: string
  delivery_kind: 'candidate_only'
  state: 'blocked'
  candidate_ready: false
  goal_completed: false
  publication_authorized: false
  execution_authorized: false
  goal_checkpoint: { goal_id: string; conversation_id: string; project_id: string; workflow_id: string | null; digest: string }
  blockers: string[]
  gaps: { code: string; blocks: string; reason: string; required_action: string; owner_actor_id: string | null; ownership_status: string }[]
  source_scans: { source_revision_id: string; source_type: string; file_count: number; file_bodies_verified: boolean;
    verified_file_count: number; verified_byte_count: number }[]
  code_analyses: { source_revision_id: string; analysis_id: string; report_hash: string; file_count: number;
    projection_status: string; build_lineage_verified?: boolean }[]
  build_lineages: { invocation_id: string; analyses: { source_revision_id: string; analysis_id: string;
    native: { generation: { generation_id: string } } | null; unused_native_generations: { generation_id: string }[] }[] }[]
  readiness: Record<'structure' | 'behavior' | 'traceability' | 'automation' | 'execution', {
    state: string; coverage: null; verified_evidence_count?: number
  }>
  budget: { goal_model_calls_used: number; goal_thinking_tokens_used: number; goal_steps_completed: number;
    goal_active_runtime_ms: number | null; cost_microusd: null; full_plan_accounting_verified: false }
  critical_conflicts: { state: 'unverified'; count: null }
}

export type BuildCompletionCommand = ToolInvocation & { result?: (NonNullable<ToolInvocation['result']> & { build_completion?: BuildCompletionReceipt }) | null }
export interface BuildCompletionObservation { command: BuildCompletionCommand; report: BuildCompletionReport | null }

export interface CompletionOwnershipPin {
  completion_invocation_id: string
  completion_report_hash: string
  revision_id: string
  revision_hash: string
}
export type OwnedBuildCompletionInput = BuildCompletionInput & { ownership_pin: CompletionOwnershipPin }
export interface OwnedBuildCompletionReport extends Omit<BuildCompletionReport, 'schema' | 'gaps'> {
  schema: 'nasus.image-build-completion.v3'
  ownership: CompletionOwnershipPin & { assignment_count: number; basis: 'confirmed_revision_not_gap_resolution' }
  gaps: (BuildCompletionReport['gaps'][number] & { gap_id: string; resolution_status: 'unresolved' })[]
}
export interface OwnedBuildCompletionObservation { command: BuildCompletionCommand; report: OwnedBuildCompletionReport | null }
