import type { AgentGoal, AgentGoalExplanation, AgentMemoryContextView, AgentSwarmRun } from '../../domains/agent/types'
import type { ProjectWorkspaceData, ReleaseReadiness } from '../../domains/quality-loop/types'
import type { ProjectCard, ToolInvocation } from '../../domains/platform/types'
import type { SystemImageData } from '../../domains/system-image/types'
import type { StudioActionId, StudioSourceBindingValues } from '../../domains/platform/tool-actions'
import type { MessageRow } from '../project-overview/ProjectWorkspaceTypes'

export type ProjectRouteContext = {
  projectId: string | null
  project: ProjectCard
  workspace?: ProjectWorkspaceData
  systemImage?: SystemImageData
  releaseReadiness?: ReleaseReadiness
  messages: MessageRow[]
  agentGoal?: AgentGoal
  agentGoalExplanation?: AgentGoalExplanation
  memoryContext?: AgentMemoryContextView
  swarmRuns: AgentSwarmRun[]
  toolInvocations: ToolInvocation[]
  pendingGoal?: AgentGoal
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  invokeProjectAction: (actionId: StudioActionId, input?: Record<string, unknown>) => void
  confirmPendingGoal: () => void
  initializeSystemImage: () => void
  buildSystemImageFromSources: (sources: StudioSourceBindingValues) => void
  confirmToolInvocation: (invocationId: string) => void
  loading: boolean
  activeActionId: string | null
}

export type ProjectRouteShellState = {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}
