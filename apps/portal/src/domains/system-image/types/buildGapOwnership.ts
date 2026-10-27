import type { AgentGoal } from '../../agent/types'
import type { ToolInvocation } from '../../platform/types/tool'

export interface GapAssignment { gap_id: string; owner_actor_id: string; reason: string }
export interface GapOwnershipInput {
  project_id: string; completion_invocation_id: string; completion_report_hash: string; expected_goal: AgentGoal
  parent_revision_id: string | null; parent_revision_hash: string | null; assignments: GapAssignment[]
}
export interface GapOwnershipRevision {
  revision_id: string; revision_hash: string; revision_number: number; invocation_id: string
  confirmed_by: string; created_at: string; assignments: GapAssignment[]
}
export interface GapOwnershipView {
  schema: 'nasus.image-build-gap-ownership.v1'; project_id: string
  completion_invocation_id: string; completion_report_hash: string
  revision_id: string | null; revision_hash: string | null; revision_number: number; is_current_revision: boolean
  gaps: { gap_id: string; code: string; blocks: string; reason: string; required_action: string
    owner_actor_id: string | null; ownership_status: 'unassigned' | 'confirmed' | 'owner_unavailable'; resolution_status: 'unresolved' }[]
  history: GapOwnershipRevision[]
  goal_completed: false; publication_authorized: false; execution_authorized: false
}
export type GapOwnershipCommand = ToolInvocation & { result?: (NonNullable<ToolInvocation['result']> & {
  build_gap_ownership?: { kind: 'build_gap_ownership'; project_id: string; completion_invocation_id: string
    completion_report_hash: string; revision_id: string; revision_hash: string }
}) | null }
export interface GapOwnerOption { actor_id: string; display_name: string }
export interface GapOwnershipObservation { view: GapOwnershipView; command: GapOwnershipCommand | null }
