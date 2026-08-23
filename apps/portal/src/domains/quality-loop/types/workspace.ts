import type { ConversationSession } from '../../agent/types'
import type { ProjectCard } from '../../platform/types'
import type { AssetLane, QualityAssetPack, QualityLoopState } from './assets'
import type { ExecutionEvidence, FailureReport, RunSummary } from './execution'
import type { ApprovalSummary, ReleaseDecision } from './governance'
import type { USItem } from './us'
import type { VersionSummary } from './version'

export interface ProjectWorkspaceData {
  project: ProjectCard
  versions: VersionSummary[]
  current_version_id: string
  us_items: USItem[]
  quality_loop_state: QualityLoopState
  quality_asset_pack?: QualityAssetPack | null
  asset_lanes: AssetLane[]
  runs: RunSummary[]
  execution_evidence: ExecutionEvidence[]
  failure_reports: FailureReport[]
  release_decision?: ReleaseDecision | null
  approvals: ApprovalSummary[]
}

export interface WorkspaceData {
  project: ProjectCard
  version: VersionSummary
  us_item: USItem
  quality_loop_state: QualityLoopState
  asset_lanes: AssetLane[]
  conversation: ConversationSession
  runs: RunSummary[]
  approvals: ApprovalSummary[]
}
