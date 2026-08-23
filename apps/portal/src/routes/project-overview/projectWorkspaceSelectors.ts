import type { AgentGoal } from '../../domains/agent/types'
import type { ProjectWorkspaceData } from '../../domains/quality-loop/types'
import type { ToolInvocation } from '../../domains/platform/types'
import type { SystemImageData } from '../../domains/system-image/types'
import type { AgentMode } from './ProjectWorkspaceTypes'

export type QualityLaneCardView = {
  id: string
  label: string
  summary: string
  status: string
  statusLabel: string
}

export type QualityLatestRunView = {
  title: string
  summary: string
  status: string
}

export type QualityLoopStateView = {
  label: string
  status: string
  releaseScore: number
  nextTool: string
  stageIndex: number
  blockers: string[]
}

export type QualityPanelHeaderView = {
  title: string
  summary: string
  qualityStatus?: string
  latestRunStatus?: string
}

export type QualityAssetPanelView = {
  header: QualityPanelHeaderView
  qualityState?: QualityLoopStateView
  lanes: QualityLaneCardView[]
  latestRun?: QualityLatestRunView
}

export function selectPendingBaselineInvocation(
  toolInvocations: ToolInvocation[],
  pendingGoal?: AgentGoal,
): ToolInvocation | undefined {
  if (pendingGoal) return undefined

  return toolInvocations
    .filter((invocation) => invocation.tool_id === 'system_image.baseline.initialize' && invocation.status === 'waiting_confirmation')
    .at(-1)
}

export function shouldShowSourceBindingPanel(
  mode: AgentMode,
  systemImage: SystemImageData | undefined,
  pendingGoal: AgentGoal | undefined,
): boolean {
  return (
    mode === 'sources' ||
    systemImage?.build_state.status === 'source_required' ||
    pendingGoal?.pause_reason === 'missing_source_binding'
  )
}

export function qualityAssetPanelModel(workspace?: ProjectWorkspaceData): QualityAssetPanelView | undefined {
  if (!workspace) return undefined

  const primaryUs = workspace.us_items[0]
  const latestRun = workspace.runs[0]
  const qualityState = workspace.quality_loop_state

  return {
    header: {
      title: primaryUs?.title ?? 'Waiting for US work item',
      summary: primaryUs
        ? `${primaryUs.status} · ${primaryUs.progress}% · ${primaryUs.next_action}`
        : 'Import US documents or build the system image to create the first work item.',
      qualityStatus: qualityState?.status,
      latestRunStatus: latestRun?.status,
    },
    qualityState: qualityState
      ? {
          label: qualityState.label,
          status: qualityState.status,
          releaseScore: qualityState.release_score || 0,
          nextTool: qualityState.next_recommended_tools[0] ?? 'none',
          stageIndex: qualityState.stage_index,
          blockers: qualityState.blockers,
        }
      : undefined,
    lanes: workspace.asset_lanes.map((lane) => ({
      id: lane.id,
      label: lane.label,
      summary: lane.summary,
      status: lane.status,
      statusLabel: humanizeStatus(lane.status),
    })),
    latestRun: latestRun
      ? {
          title: latestRun.title,
          summary: latestRun.summary,
          status: latestRun.status,
        }
      : undefined,
  }
}

function humanizeStatus(status: string): string {
  return status
    .split('_')
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(' ')
}
